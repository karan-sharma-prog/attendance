"""
Phase 8–10 Integration, Analytics, Leave/Notifications, Admin, ML Benchmark & Load Tests.
Note: Concurrent load benchmarks measure simulated ASGI client concurrency against Neon PostgreSQL,
distinct from multi-device physical classroom testing.
"""
import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone
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
async def test_phase8_analytics_export_leave_notifications_and_admin(client):
    s_auth = await _login(client, "alex.rivera@smartpresence.edu", "StudentPass@2026")
    t_auth = await _login(client, "faculty.vance@smartpresence.edu", "FacultyPass@2026")
    a_auth = await _login(client, "admin@smartpresence.edu", "AdminPass@2026")
    s_headers = {"Authorization": f"Bearer {s_auth['access_token']}"}
    t_headers = {"Authorization": f"Bearer {t_auth['access_token']}"}
    a_headers = {"Authorization": f"Bearer {a_auth['access_token']}"}

    # 1. Analytics & Export
    ana_res = await client.get("/api/v1/attendance/analytics", headers=t_headers)
    assert ana_res.status_code == 200
    ana = ana_res.json()
    assert ana["kpis"]["total_students"] >= 1
    assert len(ana["subject_breakdown"]) >= 4

    exp_res = await client.get("/api/v1/attendance/export", headers=t_headers)
    assert exp_res.status_code == 200
    assert "text/csv" in exp_res.headers["content-type"]
    assert "Record ID,Session ID" in exp_res.text

    # 2. Leave Request + Review + Notification
    now = datetime.now(timezone.utc)
    lr_res = await client.post(
        "/api/v1/leave/request",
        headers=s_headers,
        json={
            "subject_code": "CS-401",
            "start_date": now.isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
            "reason": "Medical appointment verification test.",
        },
    )
    assert lr_res.status_code == 200
    leave_id = lr_res.json()["id"]

    try:
        rev_res = await client.post(
            f"/api/v1/leave/{leave_id}/review",
            headers=t_headers,
            json={"decision": "APPROVED"},
        )
        assert rev_res.status_code == 200
        assert rev_res.json()["status"] == "APPROVED"

        notifs_res = await client.get("/api/v1/notifications", headers=s_headers)
        assert notifs_res.status_code == 200
        matching = [n for n in notifs_res.json() if "Leave Request APPROVED" in n["title"]]
        assert len(matching) >= 1

        read_res = await client.post(f"/api/v1/notifications/{matching[0]['id']}/read", headers=s_headers)
        assert read_res.status_code == 200
        assert read_res.json()["is_read"] is True

        # 3. Admin Console Overview & Policy Setting
        ov_res = await client.get("/api/v1/admin/overview", headers=a_headers)
        assert ov_res.status_code == 200
        assert len(ov_res.json()["users"]) >= 3

        pol_res = await client.put(
            "/api/v1/admin/settings",
            headers=a_headers,
            json={"key": "ATTENDANCE_WARNING_THRESHOLD_PERCENT", "value": "75.0"},
        )
        assert pol_res.status_code == 200
    finally:
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM leave_requests WHERE id = :lid"), {"lid": leave_id})
            await conn.execute(text("DELETE FROM notifications WHERE user_id = :uid"), {"uid": s_auth["user_id"]})


@pytest.mark.asyncio
async def test_phase10_simulated_concurrent_load_benchmark(client):
    """
    Simulated concurrency load test across 10, 30, and 60 parallel requests.
    """
    s_auth = await _login(client, "alex.rivera@smartpresence.edu", "StudentPass@2026")
    headers = {"Authorization": f"Bearer {s_auth['access_token']}"}

    print("\n=== Simulated Concurrent Load Benchmark (ASGI -> Neon PostgreSQL) ===")
    for concurrency in (10, 30, 60):
        latencies = []
        errors = 0

        async def _hit():
            nonlocal errors
            t0 = time.perf_counter()
            r = await client.get("/api/v1/sessions/active", headers=headers)
            latencies.append((time.perf_counter() - t0) * 1000)
            if r.status_code != 200:
                errors += 1

        t_start = time.perf_counter()
        await asyncio.gather(*[_hit() for _ in range(concurrency)])
        total_s = time.perf_counter() - t_start
        lat_sorted = sorted(latencies)
        p50 = lat_sorted[len(lat_sorted) // 2]
        p95 = lat_sorted[int(len(lat_sorted) * 0.95)]
        rps = concurrency / max(total_s, 1e-6)
        print(
            f"[Load N={concurrency:2d}] total={total_s:.2f}s | RPS={rps:.1f} | p50={p50:.1f}ms | p95={p95:.1f}ms | errors={errors}"
        )
        assert errors == 0


@pytest.mark.asyncio
async def test_timetable_csv_upload_and_cse_student_matching(client):
    """
    Verifies teacher CSV timetable upload, CSE department student enrollment matching,
    student visibility of the matched teacher schedule, and start-now session launch.
    """
    t_auth = await _login(client, "shivika@gmail.com", "teacher")
    s_auth = await _login(client, "karansharma042006@gmail.com", "12345")
    t_headers = {"Authorization": f"Bearer {t_auth['access_token']}"}
    s_headers = {"Authorization": f"Bearer {s_auth['access_token']}"}

    csv_payload = (
        "subject_code,day_of_week,start_time,end_time,room_number,qr_refresh_interval\n"
        "CS-401,Sunday,22:15,23:00,CSE-TEST-999,8\n"
    )
    created_tt_id = None
    created_sess_id = None

    try:
        up_res = await client.post(
            "/api/v1/sessions/timetables/upload-csv",
            headers=t_headers,
            json={
                "csv_content": csv_payload,
                "replace_existing": False,
                "auto_enroll_department_students": True,
            },
        )
        assert up_res.status_code == 200, up_res.text
        up_data = up_res.json()
        assert up_data["created_count"] == 1, up_data
        assert len(up_data["errors"]) == 0, up_data["errors"]

        created_tt = up_data["timetables"][0]
        created_tt_id = created_tt["id"]
        assert created_tt["subject_code"] == "CS-401"
        assert created_tt["department_code"] == "CSE"
        assert created_tt["room_number"] == "CSE-TEST-999"
        assert created_tt["matched_student_count"] >= 1

        # Teacher sees it in 'mine' scope
        mine_res = await client.get("/api/v1/sessions/timetables?scope=mine", headers=t_headers)
        assert mine_res.status_code == 200, mine_res.text
        assert any(slot["id"] == created_tt_id for slot in mine_res.json())

        # CSE student sees the matched schedule from teacher
        stu_res = await client.get("/api/v1/sessions/timetables", headers=s_headers)
        assert stu_res.status_code == 200, stu_res.text
        matched_slots = [slot for slot in stu_res.json() if slot["id"] == created_tt_id]
        assert len(matched_slots) == 1
        assert matched_slots[0]["department_code"] == "CSE"

        # Teacher launches an instant session from the uploaded timetable slot
        start_res = await client.post(
            f"/api/v1/sessions/timetables/{created_tt_id}/start-now?duration_minutes=2",
            headers=t_headers,
        )
        assert start_res.status_code == 200, start_res.text
        created_sess_id = start_res.json()["id"]
        assert start_res.json()["subject_code"] == "CS-401"
        assert start_res.json()["status"] == "ACTIVE"

        # Soft-delete via API
        del_res = await client.delete(f"/api/v1/sessions/timetables/{created_tt_id}", headers=t_headers)
        assert del_res.status_code == 200, del_res.text
    finally:
        engine = get_engine()
        async with engine.begin() as conn:
            if created_sess_id:
                await conn.execute(text("DELETE FROM attendance_sessions WHERE id = :sid"), {"sid": created_sess_id})
            if created_tt_id:
                await conn.execute(text("DELETE FROM timetables WHERE id = :tid"), {"tid": created_tt_id})
