from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import and_, func
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
import csv
import io
from backend.app.core.database import get_db
from backend.app.models.models import (
    User,
    Department,
    Teacher,
    Student,
    Subject,
    Enrollment,
    Timetable,
    AttendanceSession,
    AttendanceRecord,
    VerificationTransaction,
    AuditLog,
)
from backend.app.schemas.schemas import (
    SubjectItem,
    TimetableCreate,
    TimetableResponse,
    TimetableCsvUploadRequest,
    TimetableUploadResult,
    SessionCreate,
    SessionExtendRequest,
    SessionSummary,
    SessionDetailResponse,
    StudentInSessionItem,
    DynamicQRResponse,
)
from backend.app.api.deps import get_current_user_with_role, require_roles
from backend.app.services.qr_service import generate_dynamic_qr_for_session
from backend.app.api.websocket.live_monitor import ws_manager

router = APIRouter(prefix="/sessions", tags=["Attendance Sessions & Timetable"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _sync_expired_sessions(db: AsyncSession) -> None:
    """Close any active sessions whose server-side end_time has passed."""
    now = _utcnow()
    res = await db.execute(
        select(AttendanceSession).where(
            AttendanceSession.is_active.is_(True),
            AttendanceSession.end_time < now,
        )
    )
    expired = res.scalars().all()
    if expired:
        for sess in expired:
            sess.is_active = False
            sess.is_paused = False
            sess.status = "CLOSED"
        await db.commit()


async def _build_session_summary(sess: AttendanceSession, db: AsyncSession) -> SessionSummary:
    subj_res = await db.execute(select(Subject).where(Subject.id == sess.subject_id))
    subject = subj_res.scalar_one_or_none()

    t_res = await db.execute(select(Teacher).where(Teacher.id == sess.teacher_id))
    teacher = t_res.scalar_one_or_none()
    t_user = None
    if teacher:
        tu_res = await db.execute(select(User).where(User.id == teacher.user_id))
        t_user = tu_res.scalar_one_or_none()

    enr_res = await db.execute(select(Enrollment).where(Enrollment.subject_id == sess.subject_id))
    enrolled_ids = {e.student_id for e in enr_res.scalars().all()}

    rec_res = await db.execute(select(AttendanceRecord).where(AttendanceRecord.session_id == sess.id))
    present_ids = {
        r.student_id for r in rec_res.scalars().all() if r.status in ("PRESENT", "LATE", "MANUAL_OVERRIDE")
    }

    now = _utcnow()
    tx_res = await db.execute(
        select(VerificationTransaction).where(
            VerificationTransaction.session_id == sess.id,
            VerificationTransaction.status.in_(["ISSUED", "LIVENESS_PASSED"]),
            VerificationTransaction.expires_at > now,
        )
    )
    pending_ids = {t.student_id for t in tx_res.scalars().all()} - present_ids

    enrolled_count = len(enrolled_ids)
    present_count = len(present_ids)
    pending_count = len(pending_ids)
    absent_count = max(0, enrolled_count - present_count - pending_count)

    return SessionSummary(
        id=sess.id,
        subject_id=sess.subject_id,
        subject_code=subject.code if subject else "UNKNOWN",
        subject_name=subject.name if subject else "Unknown Subject",
        teacher_name=t_user.full_name if t_user else "Faculty",
        classroom=sess.classroom,
        start_time=sess.start_time,
        end_time=sess.end_time,
        mode=sess.mode,
        status=sess.status,
        qr_refresh_interval=sess.qr_refresh_interval,
        is_active=sess.is_active,
        is_paused=sess.is_paused,
        geofence_required=sess.geofence_required,
        geofence_lat=sess.geofence_lat,
        geofence_lng=sess.geofence_lng,
        geofence_radius_meters=sess.geofence_radius_meters,
        enrolled_count=enrolled_count,
        present_count=present_count,
        pending_count=pending_count,
        absent_count=absent_count,
        server_time=now,
    )


@router.get("/subjects", response_model=List[SubjectItem])
async def list_subjects(
    _: Tuple[User, str] = Depends(get_current_user_with_role),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(select(Subject).order_by(Subject.code))
    subjects = res.scalars().all()
    return [SubjectItem(id=s.id, code=s.code, name=s.name, credits=s.credits) for s in subjects]


DAY_NAME_MAP = {
    "0": 0, "mon": 0, "monday": 0,
    "1": 1, "tue": 1, "tuesday": 1,
    "2": 2, "wed": 2, "wednesday": 2,
    "3": 3, "thu": 3, "thursday": 3,
    "4": 4, "fri": 4, "friday": 4,
    "5": 5, "sat": 5, "saturday": 5,
    "6": 6, "sun": 6, "sunday": 6,
}


def _parse_day_of_week(raw: str) -> int:
    key = str(raw).strip().lower()
    if key in DAY_NAME_MAP:
        return DAY_NAME_MAP[key]
    raise ValueError(f"Invalid day_of_week '{raw}'. Use Monday-Sunday or 0-6.")


def _normalize_hhmm(raw: str) -> str:
    parts = str(raw).strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time '{raw}'. Expected HH:MM.")
    hh, mm = int(parts[0]), int(parts[1])
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"Time out of range '{raw}'.")
    return f"{hh:02d}:{mm:02d}"


async def _build_timetable_response(tt: Timetable, db: AsyncSession) -> TimetableResponse:
    subj = (await db.execute(select(Subject).where(Subject.id == tt.subject_id))).scalar_one_or_none()
    dept = (
        (await db.execute(select(Department).where(Department.id == subj.department_id))).scalar_one_or_none()
        if subj
        else None
    )
    teacher = (await db.execute(select(Teacher).where(Teacher.id == tt.teacher_id))).scalar_one_or_none()
    t_user = (
        (await db.execute(select(User).where(User.id == teacher.user_id))).scalar_one_or_none()
        if teacher
        else None
    )
    matched_count = int(
        (await db.execute(select(func.count(Enrollment.id)).where(Enrollment.subject_id == tt.subject_id))).scalar()
        or 0
    )
    return TimetableResponse(
        id=tt.id,
        subject_id=tt.subject_id,
        subject_code=subj.code if subj else "UNKNOWN",
        subject_name=subj.name if subj else "Unknown",
        department_code=dept.code if dept else "CSE",
        teacher_id=tt.teacher_id,
        teacher_name=t_user.full_name if t_user else "Faculty",
        day_of_week=tt.day_of_week,
        start_time=tt.start_time,
        end_time=tt.end_time,
        room_number=tt.room_number,
        auto_open_offset_minutes=tt.auto_open_offset_minutes,
        auto_close_offset_minutes=tt.auto_close_offset_minutes,
        qr_refresh_interval=tt.qr_refresh_interval,
        is_active=tt.is_active,
        matched_student_count=matched_count,
    )


async def _ensure_department_students_enrolled(subject: Subject, db: AsyncSession) -> int:
    """Matches & enrolls all students in the subject's department (e.g. CSE) into this subject."""
    dept_students = (
        await db.execute(select(Student).where(Student.department_id == subject.department_id))
    ).scalars().all()
    added = 0
    for stu in dept_students:
        existing = (
            await db.execute(
                select(Enrollment).where(
                    Enrollment.student_id == stu.id,
                    Enrollment.subject_id == subject.id,
                )
            )
        ).scalar_one_or_none()
        if not existing:
            db.add(
                Enrollment(
                    student_id=stu.id,
                    subject_id=subject.id,
                    semester=stu.semester,
                    academic_year="2026-2027",
                )
            )
            added += 1
    return added


@router.get("/timetables", response_model=List[TimetableResponse])
async def list_timetables(
    scope: str = Query(default="default", description="default | mine | department"),
    user_and_role: Tuple[User, str] = Depends(get_current_user_with_role),
    db: AsyncSession = Depends(get_db),
):
    user, role_name = user_and_role
    stmt = select(Timetable).where(Timetable.is_active.is_(True))
    if role_name == "teacher" and scope != "department":
        t_res = await db.execute(select(Teacher).where(Teacher.user_id == user.id))
        teacher = t_res.scalar_one_or_none()
        if not teacher:
            return []
        stmt = stmt.where(Timetable.teacher_id == teacher.id)
    elif role_name == "student":
        s_res = await db.execute(select(Student).where(Student.user_id == user.id))
        student = s_res.scalar_one_or_none()
        if not student:
            return []
        enr_res = await db.execute(select(Enrollment).where(Enrollment.student_id == student.id))
        subj_ids = [e.subject_id for e in enr_res.scalars().all()]
        if not subj_ids:
            return []
        stmt = stmt.where(Timetable.subject_id.in_(subj_ids))

    res = await db.execute(stmt.order_by(Timetable.day_of_week, Timetable.start_time))
    entries = res.scalars().all()
    return [await _build_timetable_response(tt, db) for tt in entries]


@router.post("/timetables", response_model=TimetableResponse)
async def create_timetable(
    req: TimetableCreate,
    user_and_role: Tuple[User, str] = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    user, role_name = user_and_role
    subj_res = await db.execute(select(Subject).where(Subject.code == req.subject_code.strip().upper()))
    subject = subj_res.scalar_one_or_none()
    if not subject:
        raise HTTPException(status_code=404, detail=f"Subject {req.subject_code} not found.")

    if role_name == "teacher":
        t_res = await db.execute(select(Teacher).where(Teacher.user_id == user.id))
        teacher = t_res.scalar_one_or_none()
    else:
        t_res = await db.execute(select(Teacher))
        teacher = t_res.scalars().first()

    if not teacher:
        raise HTTPException(status_code=400, detail="No faculty teacher profile available for timetable assignment.")

    if req.end_time <= req.start_time:
        raise HTTPException(status_code=400, detail="Timetable end_time must be after start_time.")

    existing_res = await db.execute(
        select(Timetable).where(
            Timetable.teacher_id == teacher.id,
            Timetable.day_of_week == req.day_of_week,
            Timetable.is_active.is_(True),
        )
    )
    for existing in existing_res.scalars().all():
        if not (req.end_time <= existing.start_time or req.start_time >= existing.end_time):
            raise HTTPException(
                status_code=409,
                detail=f"Schedule overlap detected with existing slot {existing.start_time}-{existing.end_time}.",
            )

    tt = Timetable(
        subject_id=subject.id,
        teacher_id=teacher.id,
        day_of_week=req.day_of_week,
        start_time=req.start_time,
        end_time=req.end_time,
        room_number=req.room_number,
        auto_open_offset_minutes=req.auto_open_offset_minutes,
        auto_close_offset_minutes=req.auto_close_offset_minutes,
        qr_refresh_interval=req.qr_refresh_interval,
    )
    db.add(tt)
    await _ensure_department_students_enrolled(subject, db)
    await db.commit()
    await db.refresh(tt)
    return await _build_timetable_response(tt, db)


async def _process_csv_timetable_upload(
    csv_text: str,
    replace_existing: bool,
    auto_enroll_department_students: bool,
    user: User,
    role_name: str,
    db: AsyncSession,
) -> TimetableUploadResult:
    if role_name == "teacher":
        teacher = (await db.execute(select(Teacher).where(Teacher.user_id == user.id))).scalar_one_or_none()
    else:
        teacher = (await db.execute(select(Teacher))).scalars().first()
    if not teacher:
        raise HTTPException(status_code=400, detail="Faculty teacher profile required to upload a timetable.")

    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="Empty or invalid CSV timetable file.")

    # Normalize column headers
    normalized_rows = []
    for raw_row in reader:
        row = {str(k).strip().lower(): (str(v).strip() if v is not None else "") for k, v in raw_row.items() if k}
        if any(row.values()):
            normalized_rows.append(row)

    if not normalized_rows:
        raise HTTPException(status_code=400, detail="CSV contains no timetable rows.")

    if replace_existing:
        old_slots = (
            await db.execute(
                select(Timetable).where(Timetable.teacher_id == teacher.id, Timetable.is_active.is_(True))
            )
        ).scalars().all()
        for slot in old_slots:
            slot.is_active = False

    created_slots: List[Timetable] = []
    errors: List[str] = []
    matched_enrolled = 0

    for idx, row in enumerate(normalized_rows, start=1):
        try:
            subj_code = (row.get("subject_code") or row.get("subject") or "").upper()
            if not subj_code:
                raise ValueError("Missing subject_code")

            subject = (await db.execute(select(Subject).where(Subject.code == subj_code))).scalar_one_or_none()
            if not subject:
                raise ValueError(f"Subject '{subj_code}' not found in institutional catalog")

            day_val = row.get("day_of_week") or row.get("day") or ""
            day_idx = _parse_day_of_week(day_val)
            start_t = _normalize_hhmm(row.get("start_time") or row.get("start") or "")
            end_t = _normalize_hhmm(row.get("end_time") or row.get("end") or "")
            if end_t <= start_t:
                raise ValueError(f"end_time ({end_t}) must be after start_time ({start_t})")

            room = row.get("room_number") or row.get("room") or "CSE Hall"
            open_off = int(row.get("auto_open_offset_minutes") or 3)
            close_off = int(row.get("auto_close_offset_minutes") or 5)
            qr_int = max(5, min(10, int(row.get("qr_refresh_interval") or 8)))

            # Overlap check against active slots for this teacher
            active_slots = (
                await db.execute(
                    select(Timetable).where(
                        Timetable.teacher_id == teacher.id,
                        Timetable.day_of_week == day_idx,
                        Timetable.is_active.is_(True),
                    )
                )
            ).scalars().all()
            for existing in active_slots:
                if not (end_t <= existing.start_time or start_t >= existing.end_time):
                    raise ValueError(f"Overlaps existing slot {existing.start_time}-{existing.end_time}")

            tt = Timetable(
                subject_id=subject.id,
                teacher_id=teacher.id,
                day_of_week=day_idx,
                start_time=start_t,
                end_time=end_t,
                room_number=room,
                auto_open_offset_minutes=open_off,
                auto_close_offset_minutes=close_off,
                qr_refresh_interval=qr_int,
            )
            db.add(tt)
            await db.flush()
            created_slots.append(tt)

            if auto_enroll_department_students:
                matched_enrolled += await _ensure_department_students_enrolled(subject, db)
        except Exception as exc:
            errors.append(f"Row {idx}: {str(exc)}")

    if created_slots:
        db.add(
            AuditLog(
                actor_id=user.id,
                action="TIMETABLE_UPLOADED",
                resource="timetables",
                details=f"created={len(created_slots)}, matched_enrollments={matched_enrolled}",
            )
        )
    await db.commit()
    for tt in created_slots:
        await db.refresh(tt)

    return TimetableUploadResult(
        created_count=len(created_slots),
        matched_students_enrolled=matched_enrolled,
        errors=errors,
        timetables=[await _build_timetable_response(tt, db) for tt in created_slots],
    )


@router.post("/timetables/upload-csv", response_model=TimetableUploadResult)
async def upload_timetable_csv_text(
    req: TimetableCsvUploadRequest,
    user_and_role: Tuple[User, str] = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    user, role_name = user_and_role
    return await _process_csv_timetable_upload(
        req.csv_content,
        req.replace_existing,
        req.auto_enroll_department_students,
        user,
        role_name,
        db,
    )


@router.post("/timetables/upload", response_model=TimetableUploadResult)
async def upload_timetable_csv_file(
    file: UploadFile = File(...),
    replace_existing: bool = Form(default=False),
    auto_enroll_department_students: bool = Form(default=True),
    user_and_role: Tuple[User, str] = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    raw_bytes = await file.read()
    try:
        csv_text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Timetable file must be UTF-8 encoded CSV.")
    user, role_name = user_and_role
    return await _process_csv_timetable_upload(
        csv_text,
        replace_existing,
        auto_enroll_department_students,
        user,
        role_name,
        db,
    )


@router.delete("/timetables/{timetable_id}")
async def delete_timetable_slot(
    timetable_id: str,
    user_and_role: Tuple[User, str] = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    user, role_name = user_and_role
    tt = (await db.execute(select(Timetable).where(Timetable.id == timetable_id))).scalar_one_or_none()
    if not tt:
        raise HTTPException(status_code=404, detail="Timetable slot not found.")
    if role_name == "teacher":
        teacher = (await db.execute(select(Teacher).where(Teacher.user_id == user.id))).scalar_one_or_none()
        if not teacher or tt.teacher_id != teacher.id:
            raise HTTPException(status_code=403, detail="Cannot delete another instructor's timetable slot.")
    tt.is_active = False
    await db.commit()
    return {"status": "DELETED", "id": timetable_id}


@router.post("/timetables/{timetable_id}/start-now", response_model=SessionSummary)
async def start_session_from_timetable(
    timetable_id: str,
    duration_minutes: int = Query(default=5, ge=1, le=180),
    user_and_role: Tuple[User, str] = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    await _sync_expired_sessions(db)
    user, role_name = user_and_role
    tt = (await db.execute(select(Timetable).where(Timetable.id == timetable_id, Timetable.is_active.is_(True)))).scalar_one_or_none()
    if not tt:
        raise HTTPException(status_code=404, detail="Timetable slot not found.")
    if role_name == "teacher":
        teacher = (await db.execute(select(Teacher).where(Teacher.user_id == user.id))).scalar_one_or_none()
        if not teacher or tt.teacher_id != teacher.id:
            raise HTTPException(status_code=403, detail="Cannot start a session for another instructor's slot.")

    now = _utcnow()
    end_time = now + timedelta(minutes=duration_minutes)
    overlap_res = await db.execute(
        select(AttendanceSession).where(
            AttendanceSession.is_active.is_(True),
            and_(AttendanceSession.start_time < end_time, AttendanceSession.end_time > now),
            (AttendanceSession.subject_id == tt.subject_id) | (AttendanceSession.teacher_id == tt.teacher_id),
        )
    )
    if overlap_res.scalars().first():
        raise HTTPException(status_code=409, detail="An active session already exists for this subject or instructor.")

    sess = AttendanceSession(
        subject_id=tt.subject_id,
        section_id=tt.section_id,
        teacher_id=tt.teacher_id,
        timetable_id=tt.id,
        classroom=tt.room_number,
        start_time=now,
        end_time=end_time,
        mode="AUTOMATIC",
        status="ACTIVE",
        qr_refresh_interval=tt.qr_refresh_interval,
        is_active=True,
        is_paused=False,
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    return await _build_session_summary(sess, db)


@router.post("/create", response_model=SessionSummary)
async def create_attendance_session(
    req: SessionCreate,
    user_and_role: Tuple[User, str] = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    await _sync_expired_sessions(db)
    user, role_name = user_and_role

    subj_res = await db.execute(select(Subject).where(Subject.code == req.subject_code))
    subject = subj_res.scalar_one_or_none()
    if not subject:
        raise HTTPException(status_code=404, detail=f"Subject {req.subject_code} not found.")

    if role_name == "teacher":
        t_res = await db.execute(select(Teacher).where(Teacher.user_id == user.id))
        teacher = t_res.scalar_one_or_none()
    else:
        t_res = await db.execute(select(Teacher))
        teacher = t_res.scalars().first()

    if not teacher:
        raise HTTPException(status_code=400, detail="Teacher profile required to create a session.")

    now = _utcnow()
    start_time = req.scheduled_start_iso or now
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    end_time = start_time + timedelta(minutes=req.duration_minutes)

    # Prevent overlapping active sessions for the same subject or teacher
    overlap_res = await db.execute(
        select(AttendanceSession).where(
            AttendanceSession.is_active.is_(True),
            and_(AttendanceSession.start_time < end_time, AttendanceSession.end_time > start_time),
            (AttendanceSession.subject_id == subject.id) | (AttendanceSession.teacher_id == teacher.id),
        )
    )
    if overlap_res.scalars().first():
        raise HTTPException(
            status_code=409,
            detail="An overlapping active attendance session already exists for this subject or teacher.",
        )

    is_scheduled = start_time > (now + timedelta(seconds=30))
    if req.geofence_required and (req.geofence_lat is None or req.geofence_lng is None):
        raise HTTPException(
            status_code=400,
            detail="Classroom latitude and longitude are required when GPS geofencing is enabled.",
        )

    session_obj = AttendanceSession(
        subject_id=subject.id,
        teacher_id=teacher.id,
        classroom=req.classroom,
        geofence_lat=req.geofence_lat,
        geofence_lng=req.geofence_lng,
        geofence_radius_meters=req.geofence_radius_meters,
        geofence_required=req.geofence_required,
        start_time=start_time,
        end_time=end_time,
        mode=req.mode.upper(),
        status="SCHEDULED" if is_scheduled else "ACTIVE",
        qr_refresh_interval=req.qr_refresh_interval,
        is_active=True,
        is_paused=False,
    )
    db.add(session_obj)
    db.add(
        AuditLog(
            actor_id=user.id,
            action="SESSION_CREATED",
            resource=f"attendance_session:{subject.code}",
            details=f"Mode={session_obj.mode}, Duration={req.duration_minutes}m",
        )
    )
    await db.commit()
    await db.refresh(session_obj)

    return await _build_session_summary(session_obj, db)


@router.get("/active", response_model=List[SessionSummary])
async def list_active_sessions(
    user_and_role: Tuple[User, str] = Depends(get_current_user_with_role),
    db: AsyncSession = Depends(get_db),
):
    await _sync_expired_sessions(db)
    user, role_name = user_and_role
    now = _utcnow()

    stmt = select(AttendanceSession).where(
        AttendanceSession.is_active.is_(True),
        AttendanceSession.end_time >= now,
    )

    if role_name == "teacher":
        t_res = await db.execute(select(Teacher).where(Teacher.user_id == user.id))
        teacher = t_res.scalar_one_or_none()
        if not teacher:
            return []
        stmt = stmt.where(AttendanceSession.teacher_id == teacher.id)
    elif role_name == "student":
        s_res = await db.execute(select(Student).where(Student.user_id == user.id))
        student = s_res.scalar_one_or_none()
        if not student:
            return []
        enr_res = await db.execute(select(Enrollment).where(Enrollment.student_id == student.id))
        subj_ids = [e.subject_id for e in enr_res.scalars().all()]
        if not subj_ids:
            return []
        stmt = stmt.where(AttendanceSession.subject_id.in_(subj_ids))

    res = await db.execute(stmt.order_by(AttendanceSession.created_at.desc()))
    sessions = res.scalars().all()
    return [await _build_session_summary(s, db) for s in sessions]


async def _get_owned_session(session_id: str, user: User, role_name: str, db: AsyncSession) -> AttendanceSession:
    res = await db.execute(select(AttendanceSession).where(AttendanceSession.id == session_id))
    sess = res.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Attendance session not found.")
    if role_name == "teacher":
        t_res = await db.execute(select(Teacher).where(Teacher.user_id == user.id))
        teacher = t_res.scalar_one_or_none()
        if not teacher or sess.teacher_id != teacher.id:
            raise HTTPException(status_code=403, detail="You do not have permission to manage another teacher's session.")
    return sess


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session_detail(
    session_id: str,
    user_and_role: Tuple[User, str] = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    await _sync_expired_sessions(db)
    user, role_name = user_and_role
    sess = await _get_owned_session(session_id, user, role_name, db)
    summary = await _build_session_summary(sess, db)

    enr_res = await db.execute(select(Enrollment).where(Enrollment.subject_id == sess.subject_id))
    enrollments = enr_res.scalars().all()
    rec_res = await db.execute(select(AttendanceRecord).where(AttendanceRecord.session_id == sess.id))
    records_by_stu = {r.student_id: r for r in rec_res.scalars().all()}
    now = _utcnow()
    tx_res = await db.execute(
        select(VerificationTransaction).where(
            VerificationTransaction.session_id == sess.id,
            VerificationTransaction.status.in_(["ISSUED", "LIVENESS_PASSED"]),
            VerificationTransaction.expires_at > now,
        )
    )
    pending_stu_ids = {t.student_id for t in tx_res.scalars().all()}

    student_items: List[StudentInSessionItem] = []
    for enr in enrollments:
        s_res = await db.execute(select(Student).where(Student.id == enr.student_id))
        stu = s_res.scalar_one_or_none()
        if not stu:
            continue
        u_res = await db.execute(select(User).where(User.id == stu.user_id))
        u = u_res.scalar_one_or_none()
        rec = records_by_stu.get(stu.id)
        if rec:
            stu_status = rec.status
            marked_at = rec.timestamp
            method = rec.verification_method
        elif stu.id in pending_stu_ids:
            stu_status = "PENDING_VERIFICATION"
            marked_at = None
            method = "QR_SCANNED"
        else:
            stu_status = "ABSENT"
            marked_at = None
            method = None
        student_items.append(
            StudentInSessionItem(
                student_id=stu.id,
                full_name=u.full_name if u else "Student",
                roll_number=stu.roll_number,
                email=u.email if u else "",
                status=stu_status,
                marked_at=marked_at,
                verification_method=method,
            )
        )

    return SessionDetailResponse(**summary.model_dump(), students=student_items)


@router.post("/{session_id}/start", response_model=SessionSummary)
async def start_or_resume_session(
    session_id: str,
    user_and_role: Tuple[User, str] = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    user, role_name = user_and_role
    sess = await _get_owned_session(session_id, user, role_name, db)
    now = _utcnow()
    if sess.end_time <= now:
        raise HTTPException(status_code=400, detail="Session window has already expired; create or extend a session.")
    sess.is_active = True
    sess.is_paused = False
    sess.status = "ACTIVE"
    if sess.start_time > now:
        sess.start_time = now
    await db.commit()
    await db.refresh(sess)
    await ws_manager.broadcast_session_event(sess.id, {"type": "session_resumed", "session_id": sess.id})
    return await _build_session_summary(sess, db)


@router.post("/{session_id}/pause", response_model=SessionSummary)
async def pause_session(
    session_id: str,
    user_and_role: Tuple[User, str] = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    user, role_name = user_and_role
    sess = await _get_owned_session(session_id, user, role_name, db)
    if not sess.is_active:
        raise HTTPException(status_code=400, detail="Cannot pause a closed session.")
    sess.is_paused = True
    sess.status = "PAUSED"
    await db.commit()
    await db.refresh(sess)
    await ws_manager.broadcast_session_event(sess.id, {"type": "session_paused", "session_id": sess.id})
    return await _build_session_summary(sess, db)


@router.post("/{session_id}/extend", response_model=SessionSummary)
async def extend_session(
    session_id: str,
    req: SessionExtendRequest,
    user_and_role: Tuple[User, str] = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    user, role_name = user_and_role
    sess = await _get_owned_session(session_id, user, role_name, db)
    now = _utcnow()
    base = sess.end_time if sess.end_time > now else now
    sess.end_time = base + timedelta(minutes=req.additional_minutes)
    sess.is_active = True
    sess.is_paused = False
    sess.status = "ACTIVE"
    await db.commit()
    await db.refresh(sess)
    await ws_manager.broadcast_session_event(
        sess.id,
        {"type": "session_extended", "session_id": sess.id, "end_time": sess.end_time.isoformat()},
    )
    return await _build_session_summary(sess, db)


@router.post("/{session_id}/close", response_model=SessionSummary)
async def close_session(
    session_id: str,
    user_and_role: Tuple[User, str] = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    user, role_name = user_and_role
    sess = await _get_owned_session(session_id, user, role_name, db)
    sess.is_active = False
    sess.is_paused = False
    sess.status = "CLOSED"
    sess.end_time = min(sess.end_time, _utcnow())
    await db.commit()
    await db.refresh(sess)
    await ws_manager.broadcast_session_event(sess.id, {"type": "session_closed", "session_id": sess.id})
    return await _build_session_summary(sess, db)


@router.get("/{session_id}/qr", response_model=DynamicQRResponse)
async def get_dynamic_qr(
    session_id: str,
    user_and_role: Tuple[User, str] = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    await _sync_expired_sessions(db)
    user, role_name = user_and_role
    sess = await _get_owned_session(session_id, user, role_name, db)
    now = _utcnow()

    if not sess.is_active or sess.status == "CLOSED" or sess.end_time < now:
        raise HTTPException(status_code=400, detail="Attendance session is closed or expired.")
    if sess.is_paused or sess.status == "PAUSED":
        raise HTTPException(status_code=400, detail="Attendance session is currently paused. Resume it to generate QR codes.")
    if sess.start_time > now:
        raise HTTPException(status_code=400, detail="Scheduled session has not started yet.")

    qr_data = await generate_dynamic_qr_for_session(sess.id, sess.qr_refresh_interval)
    return DynamicQRResponse(
        session_id=qr_data["session_id"],
        qr_url=qr_data["qr_url"],
        qr_token=qr_data["qr_token"],
        qr_image_data_url=qr_data["qr_image_data_url"],
        issued_at=qr_data["issued_at"],
        expires_at=qr_data["expires_at"],
        refresh_interval=qr_data["refresh_interval"],
        session_end_time=sess.end_time,
        server_time=now,
    )
