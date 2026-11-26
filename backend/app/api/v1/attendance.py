"""
Attendance History, Session Attendance Inspection & Auditable Corrections.
"""
from datetime import datetime, timezone
from typing import List, Tuple
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.app.core.database import get_db
from backend.app.models.models import (
    User,
    Student,
    Teacher,
    Subject,
    AttendanceSession,
    AttendanceRecord,
    AuditLog,
    Notification,
)
from backend.app.schemas.schemas import AttendanceRecordItem, AttendanceCorrectionRequest
from backend.app.api.deps import require_roles
from backend.app.api.websocket.live_monitor import ws_manager

router = APIRouter(prefix="/attendance", tags=["Attendance Records & Corrections"])


@router.get("/student", response_model=List[AttendanceRecordItem])
async def get_my_attendance_history(
    user_and_role: Tuple[User, str] = Depends(require_roles("student")),
    db: AsyncSession = Depends(get_db),
):
    user, _ = user_and_role
    s_res = await db.execute(select(Student).where(Student.user_id == user.id))
    student = s_res.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found.")

    rec_res = await db.execute(
        select(AttendanceRecord)
        .where(AttendanceRecord.student_id == student.id)
        .order_by(AttendanceRecord.timestamp.desc())
    )
    records = rec_res.scalars().all()
    out: List[AttendanceRecordItem] = []
    for r in records:
        sess_res = await db.execute(select(AttendanceSession).where(AttendanceSession.id == r.session_id))
        sess = sess_res.scalar_one_or_none()
        subj = None
        if sess:
            subj_res = await db.execute(select(Subject).where(Subject.id == sess.subject_id))
            subj = subj_res.scalar_one_or_none()
        out.append(
            AttendanceRecordItem(
                id=r.id,
                session_id=r.session_id,
                subject_code=subj.code if subj else "UNKNOWN",
                subject_name=subj.name if subj else "Unknown Subject",
                timestamp=r.timestamp,
                status=r.status,
                verification_method=r.verification_method,
                liveness_score=r.liveness_score,
                cosine_similarity=r.cosine_similarity,
                correction_reason=r.correction_reason,
            )
        )
    return out


@router.get("/session/{session_id}", response_model=List[AttendanceRecordItem])
async def get_session_attendance_records(
    session_id: str,
    user_and_role: Tuple[User, str] = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    user, role_name = user_and_role
    sess_res = await db.execute(select(AttendanceSession).where(AttendanceSession.id == session_id))
    sess = sess_res.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Attendance session not found.")

    if role_name == "teacher":
        t_res = await db.execute(select(Teacher).where(Teacher.user_id == user.id))
        teacher = t_res.scalar_one_or_none()
        if not teacher or sess.teacher_id != teacher.id:
            raise HTTPException(status_code=403, detail="Cannot access records for another instructor's session.")

    subj_res = await db.execute(select(Subject).where(Subject.id == sess.subject_id))
    subj = subj_res.scalar_one_or_none()

    rec_res = await db.execute(select(AttendanceRecord).where(AttendanceRecord.session_id == session_id))
    return [
        AttendanceRecordItem(
            id=r.id,
            session_id=r.session_id,
            subject_code=subj.code if subj else "UNKNOWN",
            subject_name=subj.name if subj else "Unknown Subject",
            timestamp=r.timestamp,
            status=r.status,
            verification_method=r.verification_method,
            liveness_score=r.liveness_score,
            cosine_similarity=r.cosine_similarity,
            correction_reason=r.correction_reason,
        )
        for r in rec_res.scalars().all()
    ]


@router.post("/correction")
async def apply_auditable_attendance_correction(
    request: Request,
    req: AttendanceCorrectionRequest,
    user_and_role: Tuple[User, str] = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    user, role_name = user_and_role
    sess_res = await db.execute(select(AttendanceSession).where(AttendanceSession.id == req.session_id))
    sess = sess_res.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Attendance session not found.")

    if role_name == "teacher":
        t_res = await db.execute(select(Teacher).where(Teacher.user_id == user.id))
        teacher = t_res.scalar_one_or_none()
        if not teacher or sess.teacher_id != teacher.id:
            raise HTTPException(status_code=403, detail="Cannot modify records for another instructor's session.")

    s_res = await db.execute(select(Student).where(Student.id == req.student_id))
    student = s_res.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")

    rec_res = await db.execute(
        select(AttendanceRecord).where(
            AttendanceRecord.session_id == sess.id,
            AttendanceRecord.student_id == student.id,
        )
    )
    record = rec_res.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if record:
        record.status = req.status
        record.correction_reason = req.correction_reason
        record.verification_method = "MANUAL_CORRECTION"
    else:
        record = AttendanceRecord(
            session_id=sess.id,
            student_id=student.id,
            timestamp=now,
            status=req.status,
            verification_method="MANUAL_CORRECTION",
            correction_reason=req.correction_reason,
        )
        db.add(record)

    db.add(
        AuditLog(
            actor_id=user.id,
            action="ATTENDANCE_MANUAL_CORRECTION",
            resource=f"session:{sess.id}:student:{student.roll_number}",
            details=f"status={req.status}, reason={req.correction_reason}",
            ip_address=request.client.host if request.client else None,
        )
    )
    db.add(
        Notification(
            user_id=student.user_id,
            title="Attendance Record Updated",
            message=f"An instructor updated your attendance to {req.status}: {req.correction_reason}",
            type="SYSTEM",
        )
    )
    await db.commit()

    await ws_manager.broadcast_session_event(
        sess.id,
        {"type": "attendance_corrected", "session_id": sess.id, "student_id": student.id, "status": req.status},
    )
    return {"status": "UPDATED", "record_status": req.status, "reason": req.correction_reason}
