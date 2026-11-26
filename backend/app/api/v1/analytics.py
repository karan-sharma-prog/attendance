"""
Phase 8: Real-Time Analytics & Attendance CSV Export Endpoints.
All statistics are computed directly from Neon PostgreSQL tables.
"""
import csv
import io
from typing import Optional, Tuple
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.app.core.database import get_db
from backend.app.models.models import (
    User,
    Student,
    Teacher,
    Subject,
    Department,
    AttendanceSession,
    AttendanceRecord,
    FaceRegistrationRequest,
    VerificationLog,
    AuditLog,
)
from backend.app.api.deps import require_roles

router = APIRouter(prefix="/attendance", tags=["Analytics & Exports"])


@router.get("/analytics")
async def get_attendance_analytics(
    subject_code: Optional[str] = Query(default=None),
    _: Tuple[User, str] = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    total_students = int((await db.execute(select(func.count(Student.id)))).scalar() or 0)
    total_teachers = int((await db.execute(select(func.count(Teacher.id)))).scalar() or 0)
    active_sessions = int(
        (await db.execute(select(func.count(AttendanceSession.id)).where(AttendanceSession.is_active.is_(True)))).scalar()
        or 0
    )
    pending_biometrics = int(
        (
            await db.execute(
                select(func.count(FaceRegistrationRequest.id)).where(
                    FaceRegistrationRequest.status == "PENDING_APPROVAL"
                )
            )
        ).scalar()
        or 0
    )

    # Subject-wise attendance chart data
    subj_stmt = select(Subject).order_by(Subject.code)
    if subject_code:
        subj_stmt = subj_stmt.where(Subject.code == subject_code)
    subjects = (await db.execute(subj_stmt)).scalars().all()

    subject_breakdown = []
    for s in subjects:
        sess_ids = [
            row[0]
            for row in (
                await db.execute(select(AttendanceSession.id).where(AttendanceSession.subject_id == s.id))
            ).all()
        ]
        sessions_count = len(sess_ids)
        present_count = 0
        if sess_ids:
            present_count = int(
                (
                    await db.execute(
                        select(func.count(AttendanceRecord.id)).where(
                            AttendanceRecord.session_id.in_(sess_ids),
                            AttendanceRecord.status.in_(["PRESENT", "LATE", "MANUAL_OVERRIDE"]),
                        )
                    )
                ).scalar()
                or 0
            )
        subject_breakdown.append(
            {
                "subject_code": s.code,
                "subject_name": s.name,
                "sessions_held": sessions_count,
                "present_records": present_count,
            }
        )

    # Department-wise count
    depts = (await db.execute(select(Department))).scalars().all()
    dept_stats = []
    for d in depts:
        stu_cnt = int(
            (await db.execute(select(func.count(Student.id)).where(Student.department_id == d.id))).scalar() or 0
        )
        dept_stats.append({"department": d.code, "name": d.name, "students": stu_cnt})

    # Verification failure & security analytics
    logs = (await db.execute(select(VerificationLog).order_by(VerificationLog.timestamp.desc()).limit(200))).scalars().all()
    event_counts: dict[str, int] = {}
    recent_security_alerts = []
    for lg in logs:
        event_counts[lg.event_type] = event_counts.get(lg.event_type, 0) + 1
        if "FAILED" in lg.event_type or "MISMATCH" in lg.event_type or "DENIED" in lg.event_type:
            if len(recent_security_alerts) < 15:
                recent_security_alerts.append(
                    {
                        "id": lg.id,
                        "event_type": lg.event_type,
                        "details": lg.details,
                        "ip_address": lg.ip_address,
                        "timestamp": lg.timestamp.isoformat() if lg.timestamp else None,
                    }
                )

    failure_chart = [{"event": k, "count": v} for k, v in event_counts.items()]

    # Recent audit logs
    audits = (await db.execute(select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(20))).scalars().all()
    audit_items = [
        {
            "id": a.id,
            "action": a.action,
            "resource": a.resource,
            "details": a.details,
            "timestamp": a.timestamp.isoformat() if a.timestamp else None,
        }
        for a in audits
    ]

    return {
        "kpis": {
            "total_students": total_students,
            "total_teachers": total_teachers,
            "active_sessions": active_sessions,
            "pending_biometric_approvals": pending_biometrics,
        },
        "subject_breakdown": subject_breakdown,
        "department_stats": dept_stats,
        "verification_events": failure_chart,
        "security_alerts": recent_security_alerts,
        "audit_logs": audit_items,
    }


@router.get("/export")
async def export_attendance_csv(
    session_id: Optional[str] = Query(default=None),
    subject_code: Optional[str] = Query(default=None),
    _: Tuple[User, str] = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AttendanceRecord).order_by(AttendanceRecord.timestamp.desc())
    if session_id:
        stmt = stmt.where(AttendanceRecord.session_id == session_id)
    elif subject_code:
        subj = (await db.execute(select(Subject).where(Subject.code == subject_code))).scalar_one_or_none()
        if subj:
            sess_ids = [
                r[0] for r in (await db.execute(select(AttendanceSession.id).where(AttendanceSession.subject_id == subj.id))).all()
            ]
            if sess_ids:
                stmt = stmt.where(AttendanceRecord.session_id.in_(sess_ids))
            else:
                stmt = stmt.where(AttendanceRecord.session_id == "__none__")

    records = (await db.execute(stmt)).scalars().all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "Record ID",
            "Session ID",
            "Subject Code",
            "Student Roll",
            "Student Name",
            "Status",
            "Method",
            "Liveness Score",
            "Cosine Similarity",
            "Timestamp (UTC)",
            "Correction Reason",
        ]
    )
    for rec in records:
        stu = (await db.execute(select(Student).where(Student.id == rec.student_id))).scalar_one_or_none()
        usr = (await db.execute(select(User).where(User.id == stu.user_id))).scalar_one_or_none() if stu else None
        sess = (await db.execute(select(AttendanceSession).where(AttendanceSession.id == rec.session_id))).scalar_one_or_none()
        subj = (
            (await db.execute(select(Subject).where(Subject.id == sess.subject_id))).scalar_one_or_none() if sess else None
        )
        writer.writerow(
            [
                rec.id,
                rec.session_id,
                subj.code if subj else "",
                stu.roll_number if stu else "",
                usr.full_name if usr else "",
                rec.status,
                rec.verification_method,
                rec.liveness_score if rec.liveness_score is not None else "",
                rec.cosine_similarity if rec.cosine_similarity is not None else "",
                rec.timestamp.isoformat() if rec.timestamp else "",
                rec.correction_reason or "",
            ]
        )

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=smartpresence_attendance_export.csv"},
    )
