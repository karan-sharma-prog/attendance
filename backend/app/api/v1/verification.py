"""
Phase 4 & Phase 7 Verification Pipeline Endpoints:
1. POST /verification/qr        -> Validates dynamic HMAC QR, enrollment, duplicates; issues VerificationTransaction.
2. POST /verification/challenge -> Returns or swaps accessible liveness challenges bound to transaction.
3. POST /verification/liveness  -> Runs BlazeFace + MediaPipe FaceLandmarker (EAR/MAR/SolvePnP) + MiniFASNetV2 + static replay guard.
4. POST /verification/identity  -> Decrypts student's approved FaceProfile (AES-256-GCM) and computes 1:1 ArcFace ResNet-100 cosine similarity.
5. POST /verification/complete  -> Server-side rule-based decision engine inserting atomic AttendanceRecord + WebSocket update.
"""
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Tuple, List
import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.security import decrypt_biometric_embedding
from backend.app.models.models import (
    User,
    Student,
    Subject,
    Enrollment,
    FaceProfile,
    AttendanceSession,
    AttendanceRecord,
    VerificationTransaction,
    VerificationLog,
)
from backend.app.schemas.schemas import (
    VerificationInitRequest,
    VerificationInitResponse,
    GeofenceVerifyRequest,
    GeofenceVerifyResponse,
    ChallengeRefreshRequest,
    LivenessVerifyRequest,
    LivenessVerifyResponse,
    IdentityVerifyRequest,
    IdentityVerifyResponse,
    CompleteVerificationRequest,
    CompleteVerificationResponse,
)
from backend.app.api.deps import require_roles, check_rate_limit
from backend.app.services.qr_service import validate_qr_token_payload
from backend.app.services.geo_service import check_geofence
from backend.app.services.redis_service import ttl_store
from backend.app.api.websocket.live_monitor import ws_manager
from backend.app.ml.quality import decode_base64_image
from backend.app.ml.face_detector import BlazeFaceService, RetinaFaceSCRFDService
from backend.app.ml.landmarker import FaceLandmarkerService, evaluate_temporal_challenges
from backend.app.ml.anti_spoofing import MiniFASNetService
from backend.app.ml.face_recognition import ArcFaceService

router = APIRouter(prefix="/verification", tags=["QR & Biometric Verification"])

CHALLENGE_POOL = [
    "blink_twice",
    "turn_head_left",
    "turn_head_right",
    "open_mouth",
    "look_straight",
]
ACCESSIBLE_CHALLENGE_POOL = ["blink_twice", "look_straight", "open_mouth"]

_blazeface = BlazeFaceService()
_landmarker = FaceLandmarkerService()
_minifasnet = MiniFASNetService()
_retinaface = RetinaFaceSCRFDService()
_arcface = ArcFaceService()


async def _get_student_and_tx(
    tx_id: str,
    user: User,
    db: AsyncSession,
    allowed_statuses: Tuple[str, ...],
) -> Tuple[Student, VerificationTransaction]:
    s_res = await db.execute(select(Student).where(Student.user_id == user.id))
    student = s_res.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=403, detail="Student academic profile not found.")

    tx_res = await db.execute(
        select(VerificationTransaction).where(
            VerificationTransaction.id == tx_id,
            VerificationTransaction.student_id == student.id,
        )
    )
    tx = tx_res.scalar_one_or_none()
    if not tx:
        raise HTTPException(status_code=404, detail="Verification transaction not found.")

    now = datetime.now(timezone.utc)
    if tx.expires_at < now:
        tx.status = "EXPIRED"
        await db.commit()
        raise HTTPException(status_code=400, detail="Verification transaction expired. Please re-scan the classroom QR.")

    if tx.status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid verification stage (current transaction status: {tx.status}).",
        )
    return student, tx


@router.post("/qr", response_model=VerificationInitResponse)
async def verify_qr_and_issue_transaction(
    request: Request,
    req: VerificationInitRequest,
    user_and_role: Tuple[User, str] = Depends(require_roles("student")),
    db: AsyncSession = Depends(get_db),
):
    await check_rate_limit(request, "qr_scan", max_requests=25, window_seconds=60)
    user, _ = user_and_role

    s_res = await db.execute(select(Student).where(Student.user_id == user.id))
    student = s_res.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=403, detail="Student academic profile not found.")

    if student.biometric_status == "SUSPENDED":
        raise HTTPException(status_code=403, detail="Your biometric status is suspended. Contact an administrator.")
    if student.biometric_status != "APPROVED" and not student.non_biometric_exempt:
        raise HTTPException(
            status_code=403,
            detail=f"Biometric profile must be approved by Authority before marking attendance (current: {student.biometric_status}).",
        )

    is_valid, reason, parsed = await validate_qr_token_payload(req.qr_token)
    if not is_valid:
        db.add(
            VerificationLog(
                student_id=student.id,
                session_id=parsed.get("session_id") if parsed else None,
                event_type="QR_VALIDATION_FAILED",
                details=reason,
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent", "")[:250],
            )
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)

    session_id = parsed["session_id"]
    nonce = parsed["nonce"]

    sess_res = await db.execute(select(AttendanceSession).where(AttendanceSession.id == session_id))
    sess = sess_res.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if not sess or not sess.is_active or sess.status == "CLOSED":
        raise HTTPException(status_code=400, detail="Attendance session is closed.")
    if sess.is_paused or sess.status == "PAUSED":
        raise HTTPException(status_code=400, detail="Attendance session is currently paused by the instructor.")
    if now < sess.start_time or now > sess.end_time:
        raise HTTPException(status_code=400, detail="Attendance window is not currently active.")

    enr_res = await db.execute(
        select(Enrollment).where(
            Enrollment.student_id == student.id,
            Enrollment.subject_id == sess.subject_id,
        )
    )
    if not enr_res.scalar_one_or_none():
        db.add(
            VerificationLog(
                student_id=student.id,
                session_id=sess.id,
                event_type="ENROLLMENT_DENIED",
                details="Student not enrolled in subject.",
                ip_address=request.client.host if request.client else None,
            )
        )
        await db.commit()
        raise HTTPException(status_code=403, detail="You are not enrolled in this subject.")

    existing_rec = await db.execute(
        select(AttendanceRecord).where(
            AttendanceRecord.session_id == sess.id,
            AttendanceRecord.student_id == student.id,
        )
    )
    if existing_rec.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Attendance is already marked for this session.")

    replay_tx = await db.execute(
        select(VerificationTransaction).where(
            VerificationTransaction.session_id == sess.id,
            VerificationTransaction.student_id == student.id,
            VerificationTransaction.qr_nonce == nonce,
            VerificationTransaction.status == "COMPLETED",
        )
    )
    if replay_tx.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="This QR nonce has already been used for a completed transaction.")

    challenges = secrets.SystemRandom().sample(CHALLENGE_POOL, k=2)
    tx_expires_at = now + timedelta(seconds=150)
    tx = VerificationTransaction(
        session_id=sess.id,
        student_id=student.id,
        qr_nonce=nonce,
        challenges_json=json.dumps(challenges),
        expires_at=tx_expires_at,
        status="ISSUED",
    )
    db.add(tx)
    db.add(
        VerificationLog(
            student_id=student.id,
            session_id=sess.id,
            event_type="QR_VERIFIED_TX_ISSUED",
            details=f"Challenges={challenges}",
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:250],
        )
    )
    await db.commit()
    await db.refresh(tx)

    subj_res = await db.execute(select(Subject).where(Subject.id == sess.subject_id))
    subject = subj_res.scalar_one_or_none()

    await ws_manager.broadcast_session_event(
        sess.id,
        {
            "type": "student_qr_verified",
            "session_id": sess.id,
            "student_id": student.id,
            "student_name": user.full_name,
            "roll_number": student.roll_number,
            "transaction_id": tx.id,
        },
    )

    return VerificationInitResponse(
        transaction_id=tx.id,
        student_id=student.id,
        session_id=sess.id,
        subject_code=subject.code if subject else "UNKNOWN",
        subject_name=subject.name if subject else "Unknown Subject",
        expires_at=tx.expires_at,
        active_challenges=challenges,
        geofence_required=sess.geofence_required,
        geofence_radius_meters=sess.geofence_radius_meters,
        next_stage="NON_BIOMETRIC_REVIEW" if student.non_biometric_exempt else "FRONT_CAMERA_LIVENESS_PENDING",
    )


@router.post("/geofence", response_model=GeofenceVerifyResponse)
async def verify_gps_geofence(
    request: Request,
    req: GeofenceVerifyRequest,
    user_and_role: Tuple[User, str] = Depends(require_roles("student")),
    db: AsyncSession = Depends(get_db),
):
    user, _ = user_and_role
    student, tx = await _get_student_and_tx(
        req.transaction_id, user, db, ("ISSUED", "LIVENESS_PASSED", "IDENTITY_MATCHED")
    )

    sess_res = await db.execute(select(AttendanceSession).where(AttendanceSession.id == tx.session_id))
    sess = sess_res.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Attendance session not found.")

    if not sess.geofence_required or sess.geofence_lat is None or sess.geofence_lng is None:
        await ttl_store.set_ex(f"tx_geofence:{tx.id}", 300, json.dumps({"verified": True, "distance": 0.0}))
        return GeofenceVerifyResponse(
            transaction_id=tx.id,
            geofence_verified=True,
            distance_meters=0.0,
            allowed_radius_meters=sess.geofence_radius_meters,
            detail="Classroom GPS geofence not enforced for this session; telemetry logged.",
        )

    within, dist_m = check_geofence(
        req.latitude,
        req.longitude,
        sess.geofence_lat,
        sess.geofence_lng,
        sess.geofence_radius_meters,
    )
    if not within:
        db.add(
            VerificationLog(
                student_id=student.id,
                session_id=sess.id,
                event_type="GEOFENCE_VIOLATION",
                details=f"distance={dist_m}m > allowed={sess.geofence_radius_meters}m",
                ip_address=request.client.host if request.client else None,
            )
        )
        await db.commit()
        raise HTTPException(
            status_code=403,
            detail=f"Outside classroom geofence ({dist_m:.1f}m away; maximum {sess.geofence_radius_meters:.0f}m allowed).",
        )

    await ttl_store.set_ex(f"tx_geofence:{tx.id}", 300, json.dumps({"verified": True, "distance": dist_m}))
    db.add(
        VerificationLog(
            student_id=student.id,
            session_id=sess.id,
            event_type="GEOFENCE_VERIFIED",
            details=f"distance={dist_m}m <= allowed={sess.geofence_radius_meters}m",
            ip_address=request.client.host if request.client else None,
        )
    )
    await db.commit()

    return GeofenceVerifyResponse(
        transaction_id=tx.id,
        geofence_verified=True,
        distance_meters=dist_m,
        allowed_radius_meters=sess.geofence_radius_meters,
        detail=f"GPS geofence verified ({dist_m:.1f}m from classroom).",
    )


@router.post("/challenge")
async def get_or_switch_challenge(
    req: ChallengeRefreshRequest,
    user_and_role: Tuple[User, str] = Depends(require_roles("student")),
    db: AsyncSession = Depends(get_db),
):
    user, _ = user_and_role
    _, tx = await _get_student_and_tx(req.transaction_id, user, db, ("ISSUED", "LIVENESS_PASSED"))

    if req.accessible_mode:
        new_challenges = secrets.SystemRandom().sample(ACCESSIBLE_CHALLENGE_POOL, k=2)
        tx.challenges_json = json.dumps(new_challenges)
        await db.commit()
        challenges = new_challenges
    else:
        challenges = json.loads(tx.challenges_json) if tx.challenges_json else ["blink_twice", "look_straight"]

    return {
        "transaction_id": tx.id,
        "active_challenges": challenges,
        "accessible_mode": req.accessible_mode,
        "expires_at": tx.expires_at,
    }


@router.post("/liveness", response_model=LivenessVerifyResponse)
async def verify_facial_liveness(
    request: Request,
    req: LivenessVerifyRequest,
    user_and_role: Tuple[User, str] = Depends(require_roles("student")),
    db: AsyncSession = Depends(get_db),
):
    await check_rate_limit(request, "liveness", max_requests=20, window_seconds=60)
    user, _ = user_and_role
    student, tx = await _get_student_and_tx(req.transaction_id, user, db, ("ISSUED",))

    if not (_blazeface.is_ready() and _landmarker.is_ready() and _minifasnet.is_ready()):
        raise HTTPException(
            status_code=503,
            detail="ML liveness models are not initialized on the server.",
        )

    # Decode all frames
    decoded_frames: List[np.ndarray] = []
    for idx, b64 in enumerate(req.frames_base64):
        bgr, _, err = decode_base64_image(b64)
        if bgr is None:
            raise HTTPException(status_code=400, detail=f"Frame {idx+1}: {err}")
        decoded_frames.append(bgr)

    # Static duplicate-frame replay check (reject identical replayed frames)
    gray_small = [cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (64, 64)).astype(np.float32) for f in decoded_frames]
    diffs = [float(np.mean(np.abs(gray_small[i + 1] - gray_small[i]))) for i in range(len(gray_small) - 1)]
    if max(diffs) < 0.35:
        db.add(
            VerificationLog(
                student_id=student.id,
                session_id=tx.session_id,
                event_type="LIVENESS_FAILED_STATIC_REPLAY",
                details=f"Max inter-frame pixel diff={max(diffs):.4f}",
                ip_address=request.client.host if request.client else None,
            )
        )
        await db.commit()
        raise HTTPException(
            status_code=400,
            detail="Static image / zero-motion replay detected. Perform natural movement during liveness capture.",
        )

    # Run BlazeFace single-face check + MediaPipe FaceLandmarker across all frames
    frame_metrics = []
    spoof_scores = []
    for idx, bgr in enumerate(decoded_frames):
        bf_dets = _blazeface.detect(bgr, min_conf=0.55)
        if len(bf_dets) == 0:
            raise HTTPException(status_code=400, detail=f"No face detected in frame {idx+1}. Keep your face centered.")
        if len(bf_dets) > 1:
            raise HTTPException(
                status_code=400,
                detail=f"Multiple faces detected ({len(bf_dets)}) in frame {idx+1}. Only one person is permitted.",
            )

        lm_res = _landmarker.analyze_frame(bgr)
        if not lm_res.get("face_detected") or lm_res.get("multiple_faces"):
            raise HTTPException(status_code=400, detail=f"Facial landmark alignment failed on frame {idx+1}.")
        frame_metrics.append(lm_res)

        # Sample MiniFASNetV2 passive anti-spoofing on first, middle, and last frame
        if idx in (0, len(decoded_frames) // 2, len(decoded_frames) - 1):
            anti = _minifasnet.predict_liveness(
                bgr, bf_dets[0]["bbox"], threshold=settings.MINIFASNET_LIVENESS_THRESHOLD
            )
            spoof_scores.append(anti["live_score"])

    avg_live_score = float(np.mean(spoof_scores)) if spoof_scores else 0.0
    passive_passed = avg_live_score >= settings.MINIFASNET_LIVENESS_THRESHOLD

    required_challenges = json.loads(tx.challenges_json) if tx.challenges_json else ["blink_twice", "look_straight"]
    challenge_eval = evaluate_temporal_challenges(
        frame_metrics,
        required_challenges,
        mar_threshold=settings.MOUTH_MAR_THRESHOLD,
    )

    if not passive_passed:
        db.add(
            VerificationLog(
                student_id=student.id,
                session_id=tx.session_id,
                event_type="LIVENESS_FAILED_SPOOF",
                details=f"MiniFASNet avg_live_score={avg_live_score:.4f}",
                ip_address=request.client.host if request.client else None,
            )
        )
        await db.commit()
        raise HTTPException(
            status_code=400,
            detail=f"Passive anti-spoofing failed (liveness={avg_live_score:.2f} < {settings.MINIFASNET_LIVENESS_THRESHOLD}). Avoid screens, printed photos, or glare.",
        )

    if not challenge_eval["passed"]:
        failed = [k for k, ok in challenge_eval["details"].items() if not ok]
        db.add(
            VerificationLog(
                student_id=student.id,
                session_id=tx.session_id,
                event_type="LIVENESS_FAILED_CHALLENGE",
                details=f"Missed={failed}, telemetry={challenge_eval.get('telemetry')}",
                ip_address=request.client.host if request.client else None,
            )
        )
        await db.commit()
        raise HTTPException(
            status_code=400,
            detail=f"Active liveness challenge incomplete ({', '.join(c.replace('_', ' ') for c in failed)}). Please retry.",
        )

    tx.status = "LIVENESS_PASSED"
    db.add(
        VerificationLog(
            student_id=student.id,
            session_id=tx.session_id,
            event_type="LIVENESS_PASSED",
            details=f"live_score={avg_live_score:.4f}, challenges={required_challenges}",
            ip_address=request.client.host if request.client else None,
        )
    )
    await db.commit()

    await ttl_store.set_ex(
        f"tx_liveness:{tx.id}",
        300,
        json.dumps({"live_score": round(avg_live_score, 4)}),
    )

    return LivenessVerifyResponse(
        transaction_id=tx.id,
        liveness_verified=True,
        passive_live_score=round(avg_live_score, 4),
        challenge_results=challenge_eval["details"],
        telemetry=challenge_eval["telemetry"],
        next_stage="IDENTITY_VERIFICATION_PENDING",
        detail="Facial liveness verified (MiniFASNet + active challenge-response).",
    )


@router.post("/identity", response_model=IdentityVerifyResponse)
async def verify_facial_identity(
    request: Request,
    req: IdentityVerifyRequest,
    user_and_role: Tuple[User, str] = Depends(require_roles("student")),
    db: AsyncSession = Depends(get_db),
):
    await check_rate_limit(request, "identity", max_requests=20, window_seconds=60)
    user, _ = user_and_role
    student, tx = await _get_student_and_tx(req.transaction_id, user, db, ("LIVENESS_PASSED",))

    if student.biometric_status != "APPROVED":
        raise HTTPException(status_code=403, detail="Biometric profile is not approved by Authority.")

    fp_res = await db.execute(
        select(FaceProfile).where(
            FaceProfile.student_id == student.id,
            FaceProfile.is_active.is_(True),
        )
    )
    face_profile = fp_res.scalar_one_or_none()
    if not face_profile:
        raise HTTPException(
            status_code=403,
            detail="No active approved ArcFace embedding found for your account. Re-enroll biometrics.",
        )

    if not (_retinaface.is_ready() and _arcface.is_ready()):
        raise HTTPException(status_code=503, detail="ArcFace / RetinaFace ML weights are not loaded.")

    bgr, _, err = decode_base64_image(req.image_base64)
    if bgr is None:
        raise HTTPException(status_code=400, detail=err)

    dets = _retinaface.detect(bgr, conf_thresh=0.5)
    if len(dets) == 0:
        raise HTTPException(status_code=400, detail="No face detected for identity matching. Look straight at the camera.")
    if len(dets) > 1:
        raise HTTPException(status_code=400, detail="Multiple faces detected. Only the account holder may verify.")

    five_pts = np.asarray(dets[0]["landmarks_5"], dtype=np.float32)
    enrolled_bytes = decrypt_biometric_embedding(face_profile.encrypted_embedding)
    match_res = _arcface.verify_1_to_1(
        bgr,
        five_pts,
        enrolled_bytes,
        threshold=settings.ARCFACE_SIMILARITY_THRESHOLD,
    )

    if not match_res["matched"]:
        db.add(
            VerificationLog(
                student_id=student.id,
                session_id=tx.session_id,
                event_type="IDENTITY_MISMATCH",
                details=f"Cosine similarity={match_res['similarity']} < threshold={match_res['threshold']}",
                ip_address=request.client.host if request.client else None,
            )
        )
        await db.commit()
        raise HTTPException(
            status_code=403,
            detail=f"Facial identity mismatch (similarity={match_res['similarity']:.3f} < threshold {match_res['threshold']:.2f}).",
        )

    tx.status = "IDENTITY_MATCHED"
    db.add(
        VerificationLog(
            student_id=student.id,
            session_id=tx.session_id,
            event_type="IDENTITY_MATCHED",
            details=f"Cosine similarity={match_res['similarity']}",
            ip_address=request.client.host if request.client else None,
        )
    )
    await db.commit()

    await ttl_store.set_ex(
        f"tx_identity:{tx.id}",
        300,
        json.dumps({"similarity": match_res["similarity"]}),
    )

    return IdentityVerifyResponse(
        transaction_id=tx.id,
        face_matched=True,
        similarity_score=match_res["similarity"],
        threshold=match_res["threshold"],
        next_stage="COMPLETE_ATTENDANCE_PENDING",
        detail="1:1 ArcFace ResNet-100 biometric match verified.",
    )


@router.post("/complete", response_model=CompleteVerificationResponse)
async def complete_attendance_decision_engine(
    request: Request,
    req: CompleteVerificationRequest,
    user_and_role: Tuple[User, str] = Depends(require_roles("student")),
    db: AsyncSession = Depends(get_db),
):
    """
    Server-side Rule-Based Decision Engine.
    Validates every credential, enrollment, biometric approval, QR transaction,
    liveness score, and ArcFace identity match before atomically recording attendance.
    """
    user, _ = user_and_role
    student, tx = await _get_student_and_tx(req.transaction_id, user, db, ("IDENTITY_MATCHED", "ISSUED"))

    # Rule 1: Student account active & biometric status valid
    if not user.is_active or student.biometric_status != "APPROVED":
        raise HTTPException(status_code=403, detail="Account or authority biometric approval invalid.")

    # Rule 2: Must have passed liveness + identity unless authority-approved non-biometric exempt
    liveness_score = None
    cosine_sim = None
    if not student.non_biometric_exempt:
        if tx.status != "IDENTITY_MATCHED":
            raise HTTPException(
                status_code=400,
                detail=f"Biometric liveness and identity verification must complete first (status: {tx.status}).",
            )
        live_raw = await ttl_store.get(f"tx_liveness:{tx.id}")
        id_raw = await ttl_store.get(f"tx_identity:{tx.id}")
        if not live_raw or not id_raw:
            raise HTTPException(
                status_code=400,
                detail="Server-side liveness/identity verification proof expired. Retry face verification.",
            )
        liveness_score = float(json.loads(live_raw)["live_score"])
        cosine_sim = float(json.loads(id_raw)["similarity"])
        if liveness_score < settings.MINIFASNET_LIVENESS_THRESHOLD or cosine_sim < settings.ARCFACE_SIMILARITY_THRESHOLD:
            raise HTTPException(status_code=403, detail="Verification thresholds not satisfied.")

    # Rule 3: Session must not have been force-closed or paused
    sess_res = await db.execute(select(AttendanceSession).where(AttendanceSession.id == tx.session_id))
    sess = sess_res.scalar_one_or_none()
    if not sess or sess.status == "CLOSED":
        raise HTTPException(status_code=400, detail="Attendance session was closed before completion.")

    # Rule 3b: Enforce GPS Geofence if configured for this session
    if sess.geofence_required:
        geo_raw = await ttl_store.get(f"tx_geofence:{tx.id}")
        if not geo_raw or not json.loads(geo_raw).get("verified"):
            raise HTTPException(
                status_code=403,
                detail="Classroom GPS geofence verification is required for this session.",
            )

    # Rule 4: Enrollment check
    enr_res = await db.execute(
        select(Enrollment).where(
            Enrollment.student_id == student.id,
            Enrollment.subject_id == sess.subject_id,
        )
    )
    if not enr_res.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Student not enrolled in this subject.")

    # Rule 5: Atomic insertion protected by uq_session_student_attendance
    now = datetime.now(timezone.utc)
    method = "QR_NON_BIOMETRIC_EXEMPT" if student.non_biometric_exempt else "QR_LIVENESS_ARCFACE"
    record = AttendanceRecord(
        session_id=sess.id,
        student_id=student.id,
        verification_transaction_id=tx.id,
        timestamp=now,
        status="PRESENT",
        verification_method=method,
        cosine_similarity=cosine_sim,
        liveness_score=liveness_score,
    )
    tx.status = "COMPLETED"
    db.add(record)
    db.add(
        VerificationLog(
            student_id=student.id,
            session_id=sess.id,
            event_type="ATTENDANCE_RECORDED",
            details=f"Method={method}, liveness={liveness_score}, similarity={cosine_sim}",
            ip_address=request.client.host if request.client else None,
        )
    )
    try:
        await db.commit()
        await db.refresh(record)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Attendance already recorded for this session.")

    subj_res = await db.execute(select(Subject).where(Subject.id == sess.subject_id))
    subject = subj_res.scalar_one_or_none()

    await ws_manager.broadcast_session_event(
        sess.id,
        {
            "type": "attendance_marked",
            "session_id": sess.id,
            "student_id": student.id,
            "student_name": user.full_name,
            "roll_number": student.roll_number,
            "status": "PRESENT",
            "timestamp": now.isoformat(),
        },
    )

    return CompleteVerificationResponse(
        attendance_record_id=record.id,
        session_id=sess.id,
        subject_code=subject.code if subject else "UNKNOWN",
        subject_name=subject.name if subject else "Unknown Subject",
        status=record.status,
        marked_at=record.timestamp,
        verification_method=method,
        liveness_score=liveness_score,
        cosine_similarity=cosine_sim,
    )
