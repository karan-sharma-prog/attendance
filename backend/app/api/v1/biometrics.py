"""
Phase 5: Student Biometric Enrollment & Authority Approval Workflow.
Enforces 5-orientation capture, real OpenCV quality checks (plus MediaPipe/ArcFace
when Phase 6 weights are loaded), AES-256-GCM encryption of reference preview
and candidate embeddings, consent/deletion rights, and Admin RBAC approval.
"""
import json
from datetime import datetime, timezone
from typing import List, Tuple
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.app.core.database import get_db
from backend.app.core.security import (
    encrypt_biometric_embedding,
    decrypt_biometric_embedding,
)
from backend.app.models.models import (
    User,
    Student,
    Department,
    FaceProfile,
    FaceRegistrationRequest,
    Notification,
    AuditLog,
)
from backend.app.schemas.schemas import (
    BiometricConsentRequest,
    FrameValidationRequest,
    FrameQualityResult,
    BiometricRegisterRequest,
    BiometricStatusResponse,
    AdminBiometricRequestItem,
    AdminApproveBiometricRequest,
    AdminRejectBiometricRequest,
    AdminSuspendBiometricRequest,
)
from backend.app.api.deps import require_roles
from backend.app.ml.quality import decode_base64_image, assess_frame_quality
from backend.app.ml.model_registry import get_ml_readiness
from backend.app.ml.face_detector import RetinaFaceSCRFDService
from backend.app.ml.face_recognition import ArcFaceService
import numpy as np

_retinaface = RetinaFaceSCRFDService()
_arcface = ArcFaceService()

student_router = APIRouter(prefix="/biometrics", tags=["Biometric Enrollment (Student)"])
admin_router = APIRouter(prefix="/admin/biometrics", tags=["Biometric Authority Approval (Admin)"])

REQUIRED_ORIENTATIONS = {"front", "left", "right", "up", "down"}


async def _get_student_for_user(user: User, db: AsyncSession) -> Student:
    res = await db.execute(select(Student).where(Student.user_id == user.id))
    stu = res.scalar_one_or_none()
    if not stu:
        raise HTTPException(status_code=404, detail="Student academic profile not found.")
    return stu


@student_router.get("/status", response_model=BiometricStatusResponse)
async def get_biometric_status(
    user_and_role: Tuple[User, str] = Depends(require_roles("student")),
    db: AsyncSession = Depends(get_db),
):
    user, _ = user_and_role
    stu = await _get_student_for_user(user, db)

    req_res = await db.execute(
        select(FaceRegistrationRequest)
        .where(FaceRegistrationRequest.student_id == stu.id)
        .order_by(FaceRegistrationRequest.created_at.desc())
    )
    latest_req = req_res.scalars().first()

    fp_res = await db.execute(select(FaceProfile).where(FaceProfile.student_id == stu.id, FaceProfile.is_active.is_(True)))
    fp = fp_res.scalar_one_or_none()

    return BiometricStatusResponse(
        student_id=stu.id,
        biometric_status=stu.biometric_status,
        biometric_consent_given=stu.biometric_consent_given,
        biometric_consent_at=stu.biometric_consent_at,
        non_biometric_exempt=stu.non_biometric_exempt,
        accommodation_reason=stu.accommodation_reason,
        latest_request_id=latest_req.id if latest_req else None,
        latest_request_status=latest_req.status if latest_req else None,
        latest_rejection_reason=latest_req.rejection_reason if latest_req else None,
        embedding_ready=bool(fp is not None or (latest_req and latest_req.embedding_ready)),
        ml_readiness=get_ml_readiness(),
    )


@student_router.post("/consent")
async def record_biometric_consent(
    req: BiometricConsentRequest,
    user_and_role: Tuple[User, str] = Depends(require_roles("student")),
    db: AsyncSession = Depends(get_db),
):
    if not req.consent_accepted:
        raise HTTPException(status_code=400, detail="Explicit consent must be accepted to enroll biometrics.")
    user, _ = user_and_role
    stu = await _get_student_for_user(user, db)
    stu.biometric_consent_given = True
    stu.biometric_consent_at = datetime.now(timezone.utc)
    db.add(
        AuditLog(
            actor_id=user.id,
            action="BIOMETRIC_CONSENT_GRANTED",
            resource=f"student:{stu.roll_number}",
        )
    )
    await db.commit()
    return {"status": "CONSENT_RECORDED", "consent_at": stu.biometric_consent_at}


@student_router.post("/validate-frame", response_model=FrameQualityResult)
async def validate_enrollment_frame(
    req: FrameValidationRequest,
    _: Tuple[User, str] = Depends(require_roles("student")),
):
    bgr, _, err = decode_base64_image(req.image_base64)
    if bgr is None:
        raise HTTPException(status_code=400, detail=err)
    result = assess_frame_quality(bgr, expected_orientation=req.orientation)
    return FrameQualityResult(**result)


async def _process_submission(
    stu: Student,
    user: User,
    req: BiometricRegisterRequest,
    request_type: str,
    db: AsyncSession,
):
    if not req.consent_accepted and not stu.biometric_consent_given:
        raise HTTPException(status_code=400, detail="Biometric processing consent is required before enrollment.")

    provided_orientations = {s.orientation for s in req.samples}
    if provided_orientations != REQUIRED_ORIENTATIONS:
        raise HTTPException(
            status_code=400,
            detail="All 5 facial orientations are required: front, left, right, up, down.",
        )

    quality_report = {}
    front_bytes = None
    for sample in req.samples:
        bgr, raw_bytes, err = decode_base64_image(sample.image_base64)
        if bgr is None:
            raise HTTPException(status_code=400, detail=f"[{sample.orientation}] {err}")
        q = assess_frame_quality(bgr, expected_orientation=sample.orientation)
        if not q["passed"]:
            raise HTTPException(
                status_code=400,
                detail=f"[{sample.orientation}] Quality check failed: {'; '.join(q['reasons'])}",
            )
        quality_report[sample.orientation] = q
        if sample.orientation == "front":
            front_bytes = raw_bytes

    if not front_bytes:
        raise HTTPException(status_code=400, detail="Front orientation image bytes missing.")

    stu.biometric_consent_given = True
    if not stu.biometric_consent_at:
        stu.biometric_consent_at = datetime.now(timezone.utc)

    # Encrypt front preview reference photo using AES-256-GCM before persisting
    encrypted_preview = encrypt_biometric_embedding(front_bytes)

    # Extract real 512-D ArcFace ResNet-100 embedding from front face when RetinaFace + ArcFace weights are loaded
    ml_state = get_ml_readiness()
    candidate_encrypted_embedding = None
    embedding_ready = False
    if _retinaface.is_ready() and _arcface.is_ready():
        front_sample = next(s for s in req.samples if s.orientation == "front")
        front_bgr, _, _ = decode_base64_image(front_sample.image_base64)
        if front_bgr is not None:
            dets = _retinaface.detect(front_bgr, conf_thresh=0.5)
            if len(dets) > 1:
                raise HTTPException(
                    status_code=400,
                    detail=f"Multiple faces detected in front enrollment image ({len(dets)}). Ensure only one face is visible.",
                )
            if len(dets) == 1:
                five_pts = np.asarray(dets[0]["landmarks_5"], dtype=np.float32)
                emb = _arcface.get_embedding(front_bgr, five_pts)
                candidate_encrypted_embedding = encrypt_biometric_embedding(emb.astype(np.float32).tobytes())
                embedding_ready = True
            else:
                raise HTTPException(
                    status_code=400,
                    detail="No face detected by RetinaFace in front enrollment image. Look straight at the camera.",
                )

    reg_req = FaceRegistrationRequest(
        student_id=stu.id,
        request_type=request_type,
        status="PENDING_APPROVAL",
        orientation_samples_meta=json.dumps(quality_report),
        encrypted_preview_image=encrypted_preview,
        candidate_encrypted_embedding=candidate_encrypted_embedding,
        embedding_ready=embedding_ready,
    )
    stu.biometric_status = "UPDATE_REQUESTED" if request_type == "UPDATE" else "PENDING_APPROVAL"

    db.add(reg_req)
    db.add(
        AuditLog(
            actor_id=user.id,
            action=f"BIOMETRIC_{request_type}_SUBMITTED",
            resource=f"student:{stu.roll_number}",
            details=f"embedding_ready={embedding_ready}",
        )
    )
    await db.commit()
    await db.refresh(reg_req)
    return reg_req


@student_router.post("/register")
async def register_biometrics(
    req: BiometricRegisterRequest,
    user_and_role: Tuple[User, str] = Depends(require_roles("student")),
    db: AsyncSession = Depends(get_db),
):
    user, _ = user_and_role
    stu = await _get_student_for_user(user, db)

    if stu.biometric_status == "APPROVED":
        raise HTTPException(
            status_code=409,
            detail="Approved biometric profiles cannot be overwritten directly. Submit a profile update request instead.",
        )
    if stu.biometric_status == "SUSPENDED":
        raise HTTPException(status_code=403, detail="Your biometric profile is suspended. Contact an administrator.")
    if stu.biometric_status in ("PENDING_APPROVAL", "UPDATE_REQUESTED"):
        raise HTTPException(status_code=409, detail="A biometric review request is already pending authority approval.")

    reg_req = await _process_submission(stu, user, req, "INITIAL", db)
    return {
        "request_id": reg_req.id,
        "biometric_status": stu.biometric_status,
        "embedding_ready": reg_req.embedding_ready,
        "message": "5-orientation facial enrollment submitted for authority review.",
    }


@student_router.post("/update-request")
async def request_biometric_update(
    req: BiometricRegisterRequest,
    user_and_role: Tuple[User, str] = Depends(require_roles("student")),
    db: AsyncSession = Depends(get_db),
):
    user, _ = user_and_role
    stu = await _get_student_for_user(user, db)

    if stu.biometric_status not in ("APPROVED", "REJECTED"):
        raise HTTPException(
            status_code=400,
            detail=f"Update requests are only available for APPROVED profiles (current status: {stu.biometric_status}).",
        )

    reg_req = await _process_submission(stu, user, req, "UPDATE", db)
    return {
        "request_id": reg_req.id,
        "biometric_status": stu.biometric_status,
        "message": "Biometric update request submitted. Existing profile stays active until authority approval.",
    }


@student_router.delete("/profile")
async def delete_biometric_profile(
    user_and_role: Tuple[User, str] = Depends(require_roles("student")),
    db: AsyncSession = Depends(get_db),
):
    """Withdraw biometric consent and permanently purge encrypted biometric profiles & preview images."""
    user, _ = user_and_role
    stu = await _get_student_for_user(user, db)

    fp_res = await db.execute(select(FaceProfile).where(FaceProfile.student_id == stu.id))
    for fp in fp_res.scalars().all():
        await db.delete(fp)

    req_res = await db.execute(select(FaceRegistrationRequest).where(FaceRegistrationRequest.student_id == stu.id))
    for r in req_res.scalars().all():
        r.encrypted_preview_image = None
        r.candidate_encrypted_embedding = None

    stu.biometric_status = "NOT_REGISTERED"
    stu.biometric_consent_given = False
    stu.biometric_consent_at = None

    db.add(
        AuditLog(
            actor_id=user.id,
            action="BIOMETRIC_DATA_DELETED",
            resource=f"student:{stu.roll_number}",
            details="Student withdrew consent and deleted biometric templates.",
        )
    )
    await db.commit()
    return {"status": "DELETED", "biometric_status": stu.biometric_status}


# ==============================================================================
# ADMIN / AUTHORITY APPROVAL WORKFLOW
# ==============================================================================

@admin_router.get("/requests", response_model=List[AdminBiometricRequestItem])
async def list_biometric_requests(
    status_filter: str | None = None,
    _: Tuple[User, str] = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(FaceRegistrationRequest).order_by(FaceRegistrationRequest.created_at.desc())
    if status_filter:
        stmt = stmt.where(FaceRegistrationRequest.status == status_filter)

    res = await db.execute(stmt)
    reqs = res.scalars().all()
    items: List[AdminBiometricRequestItem] = []

    for r in reqs:
        s_res = await db.execute(select(Student).where(Student.id == r.student_id))
        stu = s_res.scalar_one_or_none()
        if not stu:
            continue
        u_res = await db.execute(select(User).where(User.id == stu.user_id))
        u = u_res.scalar_one_or_none()
        d_res = await db.execute(select(Department).where(Department.id == stu.department_id))
        dept = d_res.scalar_one_or_none()

        meta = None
        if r.orientation_samples_meta:
            try:
                meta = json.loads(r.orientation_samples_meta)
            except Exception:
                meta = None

        items.append(
            AdminBiometricRequestItem(
                request_id=r.id,
                student_id=stu.id,
                student_name=u.full_name if u else "Unknown",
                roll_number=stu.roll_number,
                email=u.email if u else "",
                department=dept.name if dept else "CSE",
                semester=stu.semester,
                request_type=r.request_type,
                status=r.status,
                student_biometric_status=stu.biometric_status,
                embedding_ready=r.embedding_ready,
                orientation_metrics=meta,
                rejection_reason=r.rejection_reason,
                created_at=r.created_at,
            )
        )
    return items


@admin_router.get("/requests/{request_id}/preview")
async def get_biometric_preview_image(
    request_id: str,
    _: Tuple[User, str] = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(select(FaceRegistrationRequest).where(FaceRegistrationRequest.id == request_id))
    reg_req = res.scalar_one_or_none()
    if not reg_req or not reg_req.encrypted_preview_image:
        raise HTTPException(status_code=404, detail="Encrypted enrollment preview image not found.")

    plain_bytes = decrypt_biometric_embedding(reg_req.encrypted_preview_image)
    media_type = "image/png" if plain_bytes.startswith(b"\x89PNG") else "image/jpeg"
    return Response(content=plain_bytes, media_type=media_type)


@admin_router.post("/approve")
async def approve_biometric_request(
    req: AdminApproveBiometricRequest,
    request: Request,
    user_and_role: Tuple[User, str] = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    admin_user, _ = user_and_role
    res = await db.execute(select(FaceRegistrationRequest).where(FaceRegistrationRequest.id == req.request_id))
    reg_req = res.scalar_one_or_none()
    if not reg_req:
        raise HTTPException(status_code=404, detail="Biometric registration request not found.")
    if reg_req.status != "PENDING_APPROVAL":
        raise HTTPException(status_code=400, detail=f"Request already processed with status {reg_req.status}.")

    s_res = await db.execute(select(Student).where(Student.id == reg_req.student_id))
    stu = s_res.scalar_one_or_none()
    if not stu:
        raise HTTPException(status_code=404, detail="Student not found.")

    now = datetime.now(timezone.utc)
    reg_req.status = "APPROVED"
    reg_req.reviewed_by_id = admin_user.id
    reg_req.reviewed_at = now

    if req.grant_non_biometric_alternative:
        stu.non_biometric_exempt = True
        stu.accommodation_reason = req.accommodation_reason or "Authority-approved non-biometric accommodation"
        stu.biometric_status = "APPROVED"
    else:
        stu.biometric_status = "APPROVED"
        # Bind real encrypted ArcFace embedding if Phase 6 weights generated one; otherwise mark awaiting Phase 6 weight sync
        if reg_req.candidate_encrypted_embedding:
            fp_res = await db.execute(select(FaceProfile).where(FaceProfile.student_id == stu.id))
            fp = fp_res.scalar_one_or_none()
            if fp:
                fp.encrypted_embedding = reg_req.candidate_encrypted_embedding
                fp.approved_by_id = admin_user.id
                fp.approved_at = now
                fp.is_active = True
            else:
                db.add(
                    FaceProfile(
                        student_id=stu.id,
                        encrypted_embedding=reg_req.candidate_encrypted_embedding,
                        approved_by_id=admin_user.id,
                        approved_at=now,
                        is_active=True,
                    )
                )

    db.add(
        Notification(
            user_id=stu.user_id,
            title="Biometric Profile Approved",
            message="Your institutional biometric registration has been approved by the Authority.",
            type="BIOMETRIC",
        )
    )
    db.add(
        AuditLog(
            actor_id=admin_user.id,
            action="BIOMETRIC_APPROVED",
            resource=f"student:{stu.roll_number}",
            details=f"non_biometric_exempt={req.grant_non_biometric_alternative}",
            ip_address=request.client.host if request.client else None,
        )
    )
    await db.commit()
    return {"status": "APPROVED", "student_id": stu.id, "biometric_status": stu.biometric_status}


@admin_router.post("/reject")
async def reject_biometric_request(
    req: AdminRejectBiometricRequest,
    request: Request,
    user_and_role: Tuple[User, str] = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    admin_user, _ = user_and_role
    res = await db.execute(select(FaceRegistrationRequest).where(FaceRegistrationRequest.id == req.request_id))
    reg_req = res.scalar_one_or_none()
    if not reg_req:
        raise HTTPException(status_code=404, detail="Biometric registration request not found.")
    if reg_req.status != "PENDING_APPROVAL":
        raise HTTPException(status_code=400, detail=f"Request already processed with status {reg_req.status}.")

    s_res = await db.execute(select(Student).where(Student.id == reg_req.student_id))
    stu = s_res.scalar_one_or_none()
    if not stu:
        raise HTTPException(status_code=404, detail="Student not found.")

    reg_req.status = "REJECTED"
    reg_req.rejection_reason = req.rejection_reason
    reg_req.reviewed_by_id = admin_user.id
    reg_req.reviewed_at = datetime.now(timezone.utc)

    # If it was an UPDATE request on an already APPROVED student, keep existing APPROVED profile intact; otherwise REJECTED
    if reg_req.request_type == "INITIAL":
        stu.biometric_status = "REJECTED"
    else:
        stu.biometric_status = "APPROVED"

    db.add(
        Notification(
            user_id=stu.user_id,
            title="Biometric Request Rejected",
            message=f"Your biometric submission was rejected: {req.rejection_reason}",
            type="BIOMETRIC",
        )
    )
    db.add(
        AuditLog(
            actor_id=admin_user.id,
            action="BIOMETRIC_REJECTED",
            resource=f"student:{stu.roll_number}",
            details=req.rejection_reason,
            ip_address=request.client.host if request.client else None,
        )
    )
    await db.commit()
    return {"status": "REJECTED", "student_id": stu.id, "biometric_status": stu.biometric_status}


@admin_router.post("/suspend")
async def suspend_student_biometric(
    req: AdminSuspendBiometricRequest,
    request: Request,
    user_and_role: Tuple[User, str] = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    admin_user, _ = user_and_role
    s_res = await db.execute(select(Student).where(Student.id == req.student_id))
    stu = s_res.scalar_one_or_none()
    if not stu:
        raise HTTPException(status_code=404, detail="Student not found.")

    stu.biometric_status = "SUSPENDED"
    fp_res = await db.execute(select(FaceProfile).where(FaceProfile.student_id == stu.id))
    for fp in fp_res.scalars().all():
        fp.is_active = False

    db.add(
        AuditLog(
            actor_id=admin_user.id,
            action="BIOMETRIC_SUSPENDED",
            resource=f"student:{stu.roll_number}",
            details=req.reason,
            ip_address=request.client.host if request.client else None,
        )
    )
    await db.commit()
    return {"status": "SUSPENDED", "student_id": stu.id}
