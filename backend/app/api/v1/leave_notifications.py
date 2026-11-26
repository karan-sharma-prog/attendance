"""
Leave Requests & User Notifications API.
"""
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.app.core.database import get_db
from backend.app.models.models import User, Student, Subject, LeaveRequest, Notification, AuditLog
from backend.app.api.deps import get_current_user_with_role, require_roles

leave_router = APIRouter(prefix="/leave", tags=["Leave Requests"])
notif_router = APIRouter(prefix="/notifications", tags=["Notifications"])


class LeaveCreateRequest(BaseModel):
    subject_code: Optional[str] = None
    start_date: datetime
    end_date: datetime
    reason: str = Field(..., min_length=5, max_length=1000)


class LeaveReviewRequest(BaseModel):
    decision: str = Field(..., pattern="^(APPROVED|REJECTED)$")


@leave_router.post("/request")
async def submit_leave_request(
    req: LeaveCreateRequest,
    user_and_role: Tuple[User, str] = Depends(require_roles("student")),
    db: AsyncSession = Depends(get_db),
):
    user, _ = user_and_role
    stu = (await db.execute(select(Student).where(Student.user_id == user.id))).scalar_one_or_none()
    if not stu:
        raise HTTPException(status_code=404, detail="Student profile not found.")
    if req.end_date < req.start_date:
        raise HTTPException(status_code=400, detail="End date must be on or after start date.")

    subj_id = None
    if req.subject_code:
        subj = (await db.execute(select(Subject).where(Subject.code == req.subject_code))).scalar_one_or_none()
        if not subj:
            raise HTTPException(status_code=404, detail=f"Subject {req.subject_code} not found.")
        subj_id = subj.id

    lr = LeaveRequest(
        student_id=stu.id,
        subject_id=subj_id,
        start_date=req.start_date,
        end_date=req.end_date,
        reason=req.reason,
        status="PENDING",
    )
    db.add(lr)
    await db.commit()
    await db.refresh(lr)
    return {"id": lr.id, "status": lr.status}


@leave_router.get("/requests")
async def list_leave_requests(
    user_and_role: Tuple[User, str] = Depends(get_current_user_with_role),
    db: AsyncSession = Depends(get_db),
):
    user, role_name = user_and_role
    stmt = select(LeaveRequest).order_by(LeaveRequest.created_at.desc())
    if role_name == "student":
        stu = (await db.execute(select(Student).where(Student.user_id == user.id))).scalar_one_or_none()
        if not stu:
            return []
        stmt = stmt.where(LeaveRequest.student_id == stu.id)

    rows = (await db.execute(stmt)).scalars().all()
    out = []
    for r in rows:
        stu = (await db.execute(select(Student).where(Student.id == r.student_id))).scalar_one_or_none()
        usr = (await db.execute(select(User).where(User.id == stu.user_id))).scalar_one_or_none() if stu else None
        subj = (await db.execute(select(Subject).where(Subject.id == r.subject_id))).scalar_one_or_none() if r.subject_id else None
        out.append(
            {
                "id": r.id,
                "student_name": usr.full_name if usr else "Student",
                "roll_number": stu.roll_number if stu else "",
                "subject_code": subj.code if subj else "ALL",
                "start_date": r.start_date.isoformat(),
                "end_date": r.end_date.isoformat(),
                "reason": r.reason,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return out


@leave_router.post("/{leave_id}/review")
async def review_leave_request(
    leave_id: str,
    req: LeaveReviewRequest,
    user_and_role: Tuple[User, str] = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    reviewer, _ = user_and_role
    lr = (await db.execute(select(LeaveRequest).where(LeaveRequest.id == leave_id))).scalar_one_or_none()
    if not lr:
        raise HTTPException(status_code=404, detail="Leave request not found.")
    lr.status = req.decision
    lr.reviewed_by_id = reviewer.id
    lr.reviewed_at = datetime.now(timezone.utc)

    stu = (await db.execute(select(Student).where(Student.id == lr.student_id))).scalar_one_or_none()
    if stu:
        db.add(
            Notification(
                user_id=stu.user_id,
                title=f"Leave Request {req.decision}",
                message=f"Your leave request ({lr.start_date.date()} to {lr.end_date.date()}) was {req.decision.lower()}.",
                type="SYSTEM",
            )
        )
    db.add(AuditLog(actor_id=reviewer.id, action=f"LEAVE_{req.decision}", resource=f"leave:{lr.id}"))
    await db.commit()
    return {"id": lr.id, "status": lr.status}


@notif_router.get("")
async def get_my_notifications(
    user_and_role: Tuple[User, str] = Depends(get_current_user_with_role),
    db: AsyncSession = Depends(get_db),
):
    user, _ = user_and_role
    rows = (
        await db.execute(
            select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(30)
        )
    ).scalars().all()
    return [
        {
            "id": n.id,
            "title": n.title,
            "message": n.message,
            "type": n.type,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in rows
    ]


@notif_router.post("/{notif_id}/read")
async def mark_notification_read(
    notif_id: str,
    user_and_role: Tuple[User, str] = Depends(get_current_user_with_role),
    db: AsyncSession = Depends(get_db),
):
    user, _ = user_and_role
    n = (
        await db.execute(select(Notification).where(Notification.id == notif_id, Notification.user_id == user.id))
    ).scalar_one_or_none()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found.")
    n.is_read = True
    await db.commit()
    return {"id": n.id, "is_read": True}
