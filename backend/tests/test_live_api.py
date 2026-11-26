import base64
import json
import os
import sys
import time
import cv2
import numpy as np
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.app.main import app
from backend.app.core.database import get_engine


@pytest.fixture(scope="session")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _login(client: AsyncClient, identifier: str, password: str) -> dict:
    res = await client.post("/api/v1/auth/login", json={"identifier": identifier, "password": password})
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.asyncio
async def test_api_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "HEALTHY"
    assert data["app"] == "SmartPresence"
    assert "redis_connected" in data


@pytest.mark.asyncio
async def test_auth_login_me_and_refresh_rotation(client):
    student_auth = await _login(client, "alex.rivera@smartpresence.edu", "StudentPass@2026")
    assert student_auth["role"] == "student"

    me_res = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {student_auth['access_token']}"},
    )
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "alex.rivera@smartpresence.edu"

    # Refresh token rotation
    ref_res = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": student_auth["refresh_token"]},
    )
    assert ref_res.status_code == 200
    rotated = ref_res.json()
    assert rotated["access_token"] != student_auth["access_token"]

    # Reusing the old refresh token must fail
    reuse_res = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": student_auth["refresh_token"]},
    )
    assert reuse_res.status_code == 401


@pytest.mark.asyncio
async def test_faculty_and_admin_login_and_invalid_rejected(client):
    t_auth = await _login(client, "faculty.vance@smartpresence.edu", "FacultyPass@2026")
    assert t_auth["role"] == "teacher"

    a_auth = await _login(client, "admin@smartpresence.edu", "AdminPass@2026")
    assert a_auth["role"] == "admin"

    bad = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "alex.rivera@smartpresence.edu", "password": "WrongPassword123"},
    )
    assert bad.status_code == 401


@pytest.mark.asyncio
async def test_rbac_enforcement(client):
    s_auth = await _login(client, "alex.rivera@smartpresence.edu", "StudentPass@2026")
    headers = {"Authorization": f"Bearer {s_auth['access_token']}"}

    # Student cannot create attendance sessions
    sess_res = await client.post(
        "/api/v1/sessions/create",
        headers=headers,
        json={"subject_code": "CS-401", "duration_minutes": 5},
    )
    assert sess_res.status_code == 403

    # Student cannot query teacher low-attendance mailer endpoints
    mail_res = await client.post(
        "/api/v1/reports/send-low-attendance-emails",
        headers=headers,
        json={"threshold": 75.0},
    )
    assert mail_res.status_code == 403


@pytest.mark.asyncio
async def test_session_lifecycle_dynamic_qr_and_verification_flow(client):
    t_auth = await _login(client, "faculty.vance@smartpresence.edu", "FacultyPass@2026")
    s_auth = await _login(client, "alex.rivera@smartpresence.edu", "StudentPass@2026")
    t_headers = {"Authorization": f"Bearer {t_auth['access_token']}"}
    s_headers = {"Authorization": f"Bearer {s_auth['access_token']}"}

    # Pre-clean any lingering active CS-401 session before test
    active_before = await client.get("/api/v1/sessions/active", headers=t_headers)
    assert active_before.status_code == 200
    for existing in active_before.json():
        if existing["subject_code"] == "CS-401":
            await client.post(f"/api/v1/sessions/{existing['id']}/close", headers=t_headers)

    # Ensure student has APPROVED biometric status for QR scan test
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE students SET biometric_status = 'APPROVED' WHERE id = :sid"),
            {"sid": s_auth["student_id"]},
        )

    # 1. Create session (Manual 5m, 8s QR interval)
    create_res = await client.post(
        "/api/v1/sessions/create",
        headers=t_headers,
        json={"subject_code": "CS-401", "duration_minutes": 5, "qr_refresh_interval": 8, "classroom": "Hall 302"},
    )
    assert create_res.status_code == 200, create_res.text
    sess = create_res.json()
    session_id = sess["id"]
    assert sess["status"] == "ACTIVE"
    assert sess["enrolled_count"] >= 1

    try:
        # 2. Overlapping session for same subject must be rejected (409)
        overlap_res = await client.post(
            "/api/v1/sessions/create",
            headers=t_headers,
            json={"subject_code": "CS-401", "duration_minutes": 5},
        )
        assert overlap_res.status_code == 409

        # 3. Generate dynamic QR -> verify it encodes an HTTPS verification URL (not raw JSON/phone numbers)
        qr_res = await client.get(f"/api/v1/sessions/{session_id}/qr", headers=t_headers)
        assert qr_res.status_code == 200, qr_res.text
        qr_payload = qr_res.json()
        assert qr_payload["qr_image_data_url"].startswith("data:image/png;base64,")
        assert qr_payload["qr_url"].startswith("https://")
        assert "/attend/verify?token=v1." in qr_payload["qr_url"]
        assert qr_payload["qr_token"].startswith("v1.")

        # 4. Tampered QR signature rejected
        tok_parts = qr_payload["qr_token"].split(".")
        tampered_tok = f"{tok_parts[0]}.{tok_parts[1]}.{'0' * 64}"
        bad_qr_res = await client.post(
            "/api/v1/verification/qr",
            headers=s_headers,
            json={"qr_token": tampered_tok},
        )
        assert bad_qr_res.status_code == 400

        # 5. Expired QR rejected
        expired_payload = base64.urlsafe_b64encode(
            json.dumps({"sid": session_id, "iat": 1000, "exp": int(time.time()) - 10, "n": "x"}).encode()
        ).decode().rstrip("=")
        exp_qr_res = await client.post(
            "/api/v1/verification/qr",
            headers=s_headers,
            json={"qr_token": f"v1.{expired_payload}.{tok_parts[2]}"},
        )
        assert exp_qr_res.status_code == 400

        # 6. Pause session -> QR generation & scan rejected
        pause_res = await client.post(f"/api/v1/sessions/{session_id}/pause", headers=t_headers)
        assert pause_res.status_code == 200
        assert pause_res.json()["is_paused"] is True

        paused_qr = await client.get(f"/api/v1/sessions/{session_id}/qr", headers=t_headers)
        assert paused_qr.status_code == 400

        paused_scan = await client.post(
            "/api/v1/verification/qr",
            headers=s_headers,
            json={"qr_token": qr_payload["qr_token"]},
        )
        assert paused_scan.status_code == 400

        # 7. Resume & extend session -> Fetch fresh QR -> Valid student QR scan issues VerificationTransaction
        resume_res = await client.post(f"/api/v1/sessions/{session_id}/start", headers=t_headers)
        assert resume_res.status_code == 200
        extend_res = await client.post(
            f"/api/v1/sessions/{session_id}/extend",
            headers=t_headers,
            json={"additional_minutes": 2},
        )
        assert extend_res.status_code == 200

        fresh_qr_res = await client.get(f"/api/v1/sessions/{session_id}/qr", headers=t_headers)
        assert fresh_qr_res.status_code == 200
        fresh_qr_payload = fresh_qr_res.json()

        valid_scan = await client.post(
            "/api/v1/verification/qr",
            headers=s_headers,
            json={"qr_token": fresh_qr_payload["qr_url"]},
        )
        assert valid_scan.status_code == 200, valid_scan.text
        tx = valid_scan.json()
        assert tx["session_id"] == session_id
        assert len(tx["active_challenges"]) == 2
        assert tx["next_stage"] == "FRONT_CAMERA_LIVENESS_PENDING"

        # 8. Session detail shows student as PENDING_VERIFICATION
        detail_res = await client.get(f"/api/v1/sessions/{session_id}", headers=t_headers)
        assert detail_res.status_code == 200
        detail = detail_res.json()
        assert detail["pending_count"] == 1

        # 9. Close session
        close_res = await client.post(f"/api/v1/sessions/{session_id}/close", headers=t_headers)
        assert close_res.status_code == 200
        assert close_res.json()["status"] == "CLOSED"
    finally:
        # Clean up synthetic test records from Neon DB so reports remain accurate
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM verification_logs WHERE session_id = :sid"),
                {"sid": session_id},
            )
            await conn.execute(
                text("DELETE FROM verification_transactions WHERE session_id = :sid"),
                {"sid": session_id},
            )
            await conn.execute(
                text("DELETE FROM attendance_sessions WHERE id = :sid"),
                {"sid": session_id},
            )
            await conn.execute(
                text("UPDATE students SET biometric_status = 'NOT_REGISTERED' WHERE id = :sid"),
                {"sid": s_auth["student_id"]},
            )


@pytest.mark.asyncio
async def test_reports_and_mailer_with_teacher_auth(client):
    t_auth = await _login(client, "faculty.vance@smartpresence.edu", "FacultyPass@2026")
    t_headers = {"Authorization": f"Bearer {t_auth['access_token']}"}

    rep_res = await client.get("/api/v1/reports/student/CS2024-8841", headers=t_headers)
    assert rep_res.status_code == 200
    assert rep_res.json()["roll_number"] == "CS2024-8841"
    assert len(rep_res.json()["courses"]) == 4

    mail_res = await client.post(
        "/api/v1/reports/send-low-attendance-emails",
        headers=t_headers,
        json={"threshold": 75.0, "custom_message": "Mandatory faculty consultation required."},
    )
    assert mail_res.status_code == 200
    assert mail_res.json()["status"] == "COMPLETED"


def _make_jpeg_b64(dark: bool = False) -> str:
    if dark:
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        ok, buf = cv2.imencode(".jpg", img)
        assert ok
        return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")

    # Use real portrait test asset so BlazeFace + RetinaFace + ArcFace ResNet-100 execute end-to-end
    asset_path = os.path.join(os.path.dirname(__file__), "assets", "real_sample.jpg")
    with open(asset_path, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("ascii")


@pytest.mark.asyncio
async def test_phase5_biometric_enrollment_and_authority_approval_workflow(client):
    s_auth = await _login(client, "alex.rivera@smartpresence.edu", "StudentPass@2026")
    a_auth = await _login(client, "admin@smartpresence.edu", "AdminPass@2026")
    s_headers = {"Authorization": f"Bearer {s_auth['access_token']}"}
    a_headers = {"Authorization": f"Bearer {a_auth['access_token']}"}

    # Ensure clean initial state
    await client.delete("/api/v1/biometrics/profile", headers=s_headers)

    st0 = await client.get("/api/v1/biometrics/status", headers=s_headers)
    assert st0.status_code == 200
    assert st0.json()["biometric_status"] == "NOT_REGISTERED"

    # 1. Dark/blank frame rejected by real OpenCV quality gate
    dark_b64 = _make_jpeg_b64(dark=True)
    bad_frame = await client.post(
        "/api/v1/biometrics/validate-frame",
        headers=s_headers,
        json={"orientation": "front", "image_base64": dark_b64},
    )
    assert bad_frame.status_code == 200
    assert bad_frame.json()["passed"] is False
    assert len(bad_frame.json()["reasons"]) >= 1

    # 2. Sharp, well-lit frame passes OpenCV quality gate
    good_b64 = _make_jpeg_b64(dark=False)
    ok_frame = await client.post(
        "/api/v1/biometrics/validate-frame",
        headers=s_headers,
        json={"orientation": "front", "image_base64": good_b64},
    )
    assert ok_frame.status_code == 200
    assert ok_frame.json()["passed"] is True
    assert ok_frame.json()["sharpness"] > 35.0

    # 3. Student submits 5-orientation registration
    samples = [
        {"orientation": o, "image_base64": good_b64}
        for o in ("front", "left", "right", "up", "down")
    ]
    reg_res = await client.post(
        "/api/v1/biometrics/register",
        headers=s_headers,
        json={"consent_accepted": True, "samples": samples},
    )
    assert reg_res.status_code == 200, reg_res.text
    req_id = reg_res.json()["request_id"]
    assert reg_res.json()["biometric_status"] == "PENDING_APPROVAL"

    try:
        # 4. Admin lists pending requests and retrieves decrypted preview image
        list_res = await client.get("/api/v1/admin/biometrics/requests", headers=a_headers)
        assert list_res.status_code == 200
        assert any(r["request_id"] == req_id for r in list_res.json())

        prev_res = await client.get(f"/api/v1/admin/biometrics/requests/{req_id}/preview", headers=a_headers)
        assert prev_res.status_code == 200
        assert prev_res.headers["content-type"] == "image/jpeg"

        # Student cannot call admin approval endpoint (RBAC 403)
        forbid = await client.post(
            "/api/v1/admin/biometrics/approve",
            headers=s_headers,
            json={"request_id": req_id},
        )
        assert forbid.status_code == 403

        # 5. Admin approves initial enrollment
        app_res = await client.post(
            "/api/v1/admin/biometrics/approve",
            headers=a_headers,
            json={"request_id": req_id, "grant_non_biometric_alternative": False},
        )
        assert app_res.status_code == 200
        assert app_res.json()["biometric_status"] == "APPROVED"

        # 6. Approved student cannot overwrite directly without update-request (409)
        overwrite = await client.post(
            "/api/v1/biometrics/register",
            headers=s_headers,
            json={"consent_accepted": True, "samples": samples},
        )
        assert overwrite.status_code == 409

        # 7. Student submits update-request -> Admin rejects -> Existing APPROVED stays intact
        upd_res = await client.post(
            "/api/v1/biometrics/update-request",
            headers=s_headers,
            json={"consent_accepted": True, "samples": samples},
        )
        assert upd_res.status_code == 200
        upd_id = upd_res.json()["request_id"]

        rej_res = await client.post(
            "/api/v1/admin/biometrics/reject",
            headers=a_headers,
            json={"request_id": upd_id, "rejection_reason": "Lighting uneven on update photo."},
        )
        assert rej_res.status_code == 200
        assert rej_res.json()["biometric_status"] == "APPROVED"

        # 8. Student deletes biometric data cleanly
        del_res = await client.delete("/api/v1/biometrics/profile", headers=s_headers)
        assert del_res.status_code == 200
        assert del_res.json()["biometric_status"] == "NOT_REGISTERED"
    finally:
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM face_registration_requests WHERE student_id = :sid"),
                {"sid": s_auth["student_id"]},
            )
            await conn.execute(
                text("DELETE FROM notifications WHERE user_id = :uid"),
                {"uid": s_auth["user_id"]},
            )


@pytest.mark.asyncio
async def test_phase7_complete_attendance_pipeline_e2e(client):
    s_auth = await _login(client, "alex.rivera@smartpresence.edu", "StudentPass@2026")
    t_auth = await _login(client, "faculty.vance@smartpresence.edu", "FacultyPass@2026")
    a_auth = await _login(client, "admin@smartpresence.edu", "AdminPass@2026")
    s_headers = {"Authorization": f"Bearer {s_auth['access_token']}"}
    t_headers = {"Authorization": f"Bearer {t_auth['access_token']}"}
    a_headers = {"Authorization": f"Bearer {a_auth['access_token']}"}

    asset_dir = os.path.join(os.path.dirname(__file__), "assets")
    real_img = cv2.imread(os.path.join(asset_dir, "real_sample.jpg"))
    spoof_img = cv2.imread(os.path.join(asset_dir, "spoof_sample.jpg"))
    t1_img = cv2.imread(os.path.join(asset_dir, "t1.jpg"))
    assert real_img is not None and spoof_img is not None and t1_img is not None

    def to_b64(img_arr) -> str:
        ok, buf = cv2.imencode(".jpg", img_arr)
        assert ok
        return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")

    real_b64 = to_b64(real_img)
    real_v2_b64 = to_b64(np.clip(real_img.astype(np.int16) + 8, 0, 255).astype(np.uint8))
    real_v3_b64 = to_b64(np.clip(real_img.astype(np.int16) - 8, 0, 255).astype(np.uint8))

    spoof_b64 = to_b64(spoof_img)
    spoof_v2_b64 = to_b64(np.clip(spoof_img.astype(np.int16) + 8, 0, 255).astype(np.uint8))
    spoof_v3_b64 = to_b64(np.clip(spoof_img.astype(np.int16) - 8, 0, 255).astype(np.uint8))

    # Crop distinct person face from t1.jpg for impostor test
    from backend.app.ml.face_detector import RetinaFaceSCRFDService
    det = RetinaFaceSCRFDService()
    t1_dets = det.detect(t1_img)
    x1, y1, x2, y2 = t1_dets[0]["bbox"]
    pad = 40
    impostor_crop = t1_img[max(0, y1 - pad) : min(t1_img.shape[0], y2 + pad), max(0, x1 - pad) : min(t1_img.shape[1], x2 + pad)]
    impostor_b64 = to_b64(impostor_crop)

    # 1. Enroll & Approve Student Biometric Profile (binds real ArcFace 512-D embedding)
    await client.delete("/api/v1/biometrics/profile", headers=s_headers)
    samples = [{"orientation": o, "image_base64": real_b64} for o in ("front", "left", "right", "up", "down")]
    reg_res = await client.post("/api/v1/biometrics/register", headers=s_headers, json={"consent_accepted": True, "samples": samples})
    assert reg_res.status_code == 200, reg_res.text
    req_id = reg_res.json()["request_id"]
    app_res = await client.post("/api/v1/admin/biometrics/approve", headers=a_headers, json={"request_id": req_id})
    assert app_res.status_code == 200

    # 2. Teacher starts live CS-401 session & generates dynamic QR
    active_before = await client.get("/api/v1/sessions/active", headers=t_headers)
    for existing in active_before.json():
        if existing["subject_code"] == "CS-401":
            await client.post(f"/api/v1/sessions/{existing['id']}/close", headers=t_headers)

    sess_res = await client.post(
        "/api/v1/sessions/create",
        headers=t_headers,
        json={
            "subject_code": "CS-401",
            "duration_minutes": 5,
            "geofence_required": True,
            "geofence_lat": 28.6139,
            "geofence_lng": 77.2090,
            "geofence_radius_meters": 100.0,
        },
    )
    assert sess_res.status_code == 200, sess_res.text
    session_id = sess_res.json()["id"]

    try:
        qr_res = await client.get(f"/api/v1/sessions/{session_id}/qr", headers=t_headers)
        assert qr_res.status_code == 200
        qr_url = qr_res.json()["qr_url"]
        assert qr_url.startswith("https://") and "/attend/verify?token=v1." in qr_url

        # 3. Student scans full QR URL -> receives VerificationTransaction with geofence_required=True
        tx_res = await client.post("/api/v1/verification/qr", headers=s_headers, json={"qr_token": qr_url})
        assert tx_res.status_code == 200, tx_res.text
        assert tx_res.json()["geofence_required"] is True
        tx_id = tx_res.json()["transaction_id"]

        # 3b. Security Test: Outside GPS geofence -> rejected (403)
        out_geo = await client.post(
            "/api/v1/verification/geofence",
            headers=s_headers,
            json={"transaction_id": tx_id, "latitude": 28.6250, "longitude": 77.2250},
        )
        assert out_geo.status_code == 403
        assert "geofence" in out_geo.json()["detail"].lower()

        # Test accessible challenge endpoint
        ch_res = await client.post("/api/v1/verification/challenge", headers=s_headers, json={"transaction_id": tx_id, "accessible_mode": True})
        assert ch_res.status_code == 200
        assert len(ch_res.json()["active_challenges"]) == 2

        # 4. Security Test A: Static duplicate frame replay -> rejected (400)
        replay_res = await client.post(
            "/api/v1/verification/liveness",
            headers=s_headers,
            json={"transaction_id": tx_id, "frames_base64": [real_b64, real_b64, real_b64]},
        )
        assert replay_res.status_code == 400
        assert "Static image" in replay_res.json()["detail"]

        # 5. Security Test B: Printed/screen spoof photo (spoof_sample.jpg) -> rejected by MiniFASNetV2 (400)
        spoof_res = await client.post(
            "/api/v1/verification/liveness",
            headers=s_headers,
            json={"transaction_id": tx_id, "frames_base64": [spoof_b64, spoof_v2_b64, spoof_v3_b64]},
        )
        assert spoof_res.status_code == 400
        assert "anti-spoofing" in spoof_res.json()["detail"].lower()

        # Bind turn_head_left challenge on test tx (matches real_sample.jpg measured SolvePnP yaw=-39.89 deg)
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE verification_transactions SET challenges_json = '[\"turn_head_left\"]' WHERE id = :tid"),
                {"tid": tx_id},
            )

        # 6. Genuine Multi-Frame Liveness Pass (BlazeFace + MediaPipe + MiniFASNetV2)
        live_res = await client.post(
            "/api/v1/verification/liveness",
            headers=s_headers,
            json={"transaction_id": tx_id, "frames_base64": [real_b64, real_v2_b64, real_v3_b64]},
        )
        assert live_res.status_code == 200, live_res.text
        assert live_res.json()["liveness_verified"] is True
        assert live_res.json()["passive_live_score"] >= 0.85

        # 7. Security Test C: Impostor face identity -> rejected by ArcFace ResNet-100 (403)
        imp_res = await client.post(
            "/api/v1/verification/identity",
            headers=s_headers,
            json={"transaction_id": tx_id, "image_base64": impostor_b64},
        )
        assert imp_res.status_code == 403
        assert "mismatch" in imp_res.json()["detail"].lower()

        # 8. Genuine 1:1 ArcFace Identity Match
        id_res = await client.post(
            "/api/v1/verification/identity",
            headers=s_headers,
            json={"transaction_id": tx_id, "image_base64": real_b64},
        )
        assert id_res.status_code == 200, id_res.text
        assert id_res.json()["face_matched"] is True
        assert id_res.json()["similarity_score"] >= 0.90

        # 9. Atomic Decision Engine -> Must fail (403) until GPS geofence verified, then pass!
        no_geo_comp = await client.post("/api/v1/verification/complete", headers=s_headers, json={"transaction_id": tx_id})
        assert no_geo_comp.status_code == 403

        in_geo = await client.post(
            "/api/v1/verification/geofence",
            headers=s_headers,
            json={"transaction_id": tx_id, "latitude": 28.6141, "longitude": 77.2092},
        )
        assert in_geo.status_code == 200
        assert in_geo.json()["geofence_verified"] is True
        assert in_geo.json()["distance_meters"] < 100.0

        comp_res = await client.post("/api/v1/verification/complete", headers=s_headers, json={"transaction_id": tx_id})
        assert comp_res.status_code == 200, comp_res.text
        assert comp_res.json()["status"] == "PRESENT"
        assert comp_res.json()["verification_method"] == "QR_LIVENESS_ARCFACE"

        # 10. Duplicate Attendance Attempt Rejected (409)
        qr_res2 = await client.get(f"/api/v1/sessions/{session_id}/qr", headers=t_headers)
        dup_scan = await client.post("/api/v1/verification/qr", headers=s_headers, json={"qr_token": qr_res2.json()["qr_token"]})
        assert dup_scan.status_code == 409

        # 11. Student Attendance History + Teacher Auditable Correction
        hist_res = await client.get("/api/v1/attendance/student", headers=s_headers)
        assert hist_res.status_code == 200
        assert any(r["session_id"] == session_id for r in hist_res.json())

        corr_res = await client.post(
            "/api/v1/attendance/correction",
            headers=t_headers,
            json={
                "session_id": session_id,
                "student_id": s_auth["student_id"],
                "status": "MANUAL_OVERRIDE",
                "correction_reason": "Verified late entry accommodation by instructor.",
            },
        )
        assert corr_res.status_code == 200
        assert corr_res.json()["record_status"] == "MANUAL_OVERRIDE"
    finally:
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM attendance_records WHERE session_id = :sid"), {"sid": session_id})
            await conn.execute(text("DELETE FROM verification_logs WHERE session_id = :sid"), {"sid": session_id})
            await conn.execute(text("DELETE FROM verification_transactions WHERE session_id = :sid"), {"sid": session_id})
            await conn.execute(text("DELETE FROM attendance_sessions WHERE id = :sid"), {"sid": session_id})
            await conn.execute(text("DELETE FROM face_profiles WHERE student_id = :stid"), {"stid": s_auth["student_id"]})
            await conn.execute(text("DELETE FROM face_registration_requests WHERE student_id = :stid"), {"stid": s_auth["student_id"]})
            await conn.execute(text("DELETE FROM notifications WHERE user_id = :uid"), {"uid": s_auth["user_id"]})
            await conn.execute(text("UPDATE students SET biometric_status = 'NOT_REGISTERED', biometric_consent_given = FALSE WHERE id = :stid"), {"stid": s_auth["student_id"]})
