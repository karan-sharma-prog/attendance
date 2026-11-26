from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Tuple
from backend.app.core.database import get_db
from backend.app.core.config import settings
from backend.app.models.models import (
    User,
    Department,
    Student,
    AttendanceRecord,
    AttendanceSession,
    Subject,
    Enrollment,
    Notification,
)
from backend.app.schemas.schemas import (
    IndividualStudentReportResponse,
    StudentAttendanceReportItem,
    LowAttendanceStudentItem,
    LowAttendanceEmailRequest,
)
from backend.app.api.deps import get_current_user_with_role, require_roles
from backend.app.services.email_service import send_low_attendance_email

router = APIRouter(prefix="/reports", tags=["Reports & Low-Attendance Alerts"])


async def _compute_student_report(student: Student, db: AsyncSession) -> IndividualStudentReportResponse:
    user_res = await db.execute(select(User).where(User.id == student.user_id))
    user = user_res.scalar_one_or_none()

    dept_res = await db.execute(select(Department).where(Department.id == student.department_id))
    dept = dept_res.scalar_one_or_none()

    enrollments_res = await db.execute(select(Enrollment).where(Enrollment.student_id == student.id))
    enrollments = enrollments_res.scalars().all()

    course_items: List[StudentAttendanceReportItem] = []
    total_all_classes = 0
    attended_all_classes = 0

    for enr in enrollments:
        subj_res = await db.execute(select(Subject).where(Subject.id == enr.subject_id))
        subject = subj_res.scalar_one_or_none()
        if not subject:
            continue

        sessions_res = await db.execute(
            select(AttendanceSession).where(AttendanceSession.subject_id == subject.id)
        )
        sessions = sessions_res.scalars().all()
        total_classes = len(sessions)

        attended_count = 0
        if total_classes > 0:
            session_ids = [s.id for s in sessions]
            records_res = await db.execute(
                select(AttendanceRecord).where(
                    AttendanceRecord.student_id == student.id,
                    AttendanceRecord.session_id.in_(session_ids),
                    AttendanceRecord.status.in_(["PRESENT", "LATE", "MANUAL_OVERRIDE"]),
                )
            )
            attended_count = len(records_res.scalars().all())

        pct = (attended_count / total_classes * 100.0) if total_classes > 0 else 100.0
        total_all_classes += total_classes
        attended_all_classes += attended_count

        course_items.append(
            StudentAttendanceReportItem(
                subject_id=subject.id,
                subject_code=subject.code,
                subject_name=subject.name,
                total_classes=total_classes,
                attended_classes=attended_count,
                attendance_percentage=round(pct, 1),
                is_at_risk=(total_classes > 0 and pct < settings.ATTENDANCE_WARNING_THRESHOLD_PERCENT),
            )
        )

    overall_pct = (attended_all_classes / total_all_classes * 100.0) if total_all_classes > 0 else 100.0

    return IndividualStudentReportResponse(
        student_id=student.id,
        student_name=user.full_name if user else "Unknown Student",
        roll_number=student.roll_number,
        enrollment_id=user.enrollment_id if user and user.enrollment_id else student.roll_number,
        department=dept.name if dept else "Unassigned",
        overall_percentage=round(overall_pct, 1),
        is_overall_at_risk=(total_all_classes > 0 and overall_pct < settings.ATTENDANCE_WARNING_THRESHOLD_PERCENT),
        courses=course_items,
    )


@router.get("/student/me", response_model=IndividualStudentReportResponse)
async def get_my_student_report(
    user_and_role: Tuple[User, str] = Depends(require_roles("student")),
    db: AsyncSession = Depends(get_db),
):
    user, _ = user_and_role
    res = await db.execute(select(Student).where(Student.user_id == user.id))
    student = res.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found")
    return await _compute_student_report(student, db)


@router.get("/student/{identifier}", response_model=IndividualStudentReportResponse)
async def get_individual_student_report(
    identifier: str,
    user_and_role: Tuple[User, str] = Depends(get_current_user_with_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Fetches the comprehensive individual student attendance report by student UUID or roll_number.
    Students may only view their own report; teachers and admins may view any student.
    """
    user, role_name = user_and_role
    res = await db.execute(
        select(Student).where((Student.id == identifier) | (Student.roll_number == identifier))
    )
    student = res.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student record not found")

    if role_name == "student" and student.user_id != user.id:
        raise HTTPException(status_code=403, detail="Students can only access their own attendance report.")

    return await _compute_student_report(student, db)


@router.get("/low-attendance", response_model=List[LowAttendanceStudentItem])
async def get_low_attendance_students(
    threshold: float = Query(default=75.0, ge=1.0, le=100.0),
    _: Tuple[User, str] = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Lists all students whose actual attendance in any enrolled subject with >=1 held class is below threshold."""
    students_res = await db.execute(select(Student))
    students = students_res.scalars().all()
    at_risk: List[LowAttendanceStudentItem] = []

    for stu in students:
        report = await _compute_student_report(stu, db)
        u_res = await db.execute(select(User).where(User.id == stu.user_id))
        user = u_res.scalar_one_or_none()
        if not user:
            continue
        for course in report.courses:
            if course.total_classes > 0 and course.attendance_percentage < threshold:
                at_risk.append(
                    LowAttendanceStudentItem(
                        student_id=stu.id,
                        student_name=report.student_name,
                        roll_number=report.roll_number,
                        email=user.email,
                        subject_name=f"{course.subject_code}: {course.subject_name}",
                        attended_classes=course.attended_classes,
                        total_classes=course.total_classes,
                        attendance_percentage=course.attendance_percentage,
                    )
                )
    return at_risk


@router.post("/send-low-attendance-emails")
async def dispatch_low_attendance_warning_emails(
    req: LowAttendanceEmailRequest,
    _: Tuple[User, str] = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    Identifies students falling below the specified threshold from live PostgreSQL records
    and dispatches direct warning emails via SMTP (or logs transparently if SMTP isn't configured).
    """
    stmt = select(Student)
    if req.student_ids:
        stmt = stmt.where(Student.id.in_(req.student_ids))
    students_res = await db.execute(stmt)
    students = students_res.scalars().all()

    smtp_configured = bool(settings.SMTP_USER and settings.SMTP_PASSWORD)
    dispatched = []

    for stu in students:
        user_res = await db.execute(select(User).where(User.id == stu.user_id))
        user = user_res.scalar_one_or_none()
        if not user or not user.email:
            continue

        report = await _compute_student_report(stu, db)
        # Check courses below threshold (or overall if specific student_ids requested with 0 sessions)
        low_courses = [
            c for c in report.courses if c.total_classes > 0 and c.attendance_percentage < req.threshold
        ]
        if not low_courses and not req.student_ids:
            continue

        target_subject = (
            ", ".join(f"{c.subject_code} ({c.attendance_percentage}%)" for c in low_courses)
            if low_courses
            else "Enrolled Academic Courses"
        )
        pct = min((c.attendance_percentage for c in low_courses), default=report.overall_percentage)

        sent_ok = await send_low_attendance_email(
            to_email=user.email,
            student_name=user.full_name,
            subject_name=target_subject,
            attendance_percentage=pct,
            threshold=req.threshold,
            custom_note=req.custom_message or "",
        )
        if sent_ok:
            db.add(
                Notification(
                    user_id=user.id,
                    title="Low Attendance Warning",
                    message=f"Your attendance in {target_subject} is {pct:.1f}% (below {req.threshold:.0f}%).",
                    type="ATTENDANCE_ALERT",
                )
            )
            dispatched.append(
                {
                    "student_id": stu.id,
                    "email": user.email,
                    "percentage": pct,
                    "status": "SENT" if smtp_configured else "LOGGED_SMTP_UNCONFIGURED",
                }
            )

    await db.commit()

    return {
        "status": "COMPLETED",
        "smtp_configured": smtp_configured,
        "total_dispatched": len(dispatched),
        "details": dispatched,
    }
