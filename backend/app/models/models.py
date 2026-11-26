import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Boolean, Integer, Float, DateTime, ForeignKey,
    Text, LargeBinary, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from backend.app.core.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Role(Base):
    __tablename__ = "roles"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(50), unique=True, nullable=False, index=True)  # student, teacher, admin
    description = Column(String(255), nullable=True)
    users = relationship("User", back_populates="role")


class User(Base):
    __tablename__ = "users"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    enrollment_id = Column(String(100), unique=True, nullable=True, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role_id = Column(String(36), ForeignKey("roles.id"), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    role = relationship("Role", back_populates="users")
    student_profile = relationship("Student", back_populates="user", uselist=False)
    teacher_profile = relationship("Teacher", back_populates="user", uselist=False)


class Department(Base):
    __tablename__ = "departments"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(150), unique=True, nullable=False)
    code = Column(String(20), unique=True, nullable=False, index=True)
    students = relationship("Student", back_populates="department")
    teachers = relationship("Teacher", back_populates="department")
    subjects = relationship("Subject", back_populates="department")


class Section(Base):
    __tablename__ = "sections"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(50), nullable=False)
    department_id = Column(String(36), ForeignKey("departments.id"), nullable=False)
    semester = Column(Integer, nullable=False)


class Subject(Base):
    __tablename__ = "subjects"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(200), nullable=False)
    code = Column(String(50), unique=True, nullable=False, index=True)
    department_id = Column(String(36), ForeignKey("departments.id"), nullable=False)
    credits = Column(Integer, default=3, nullable=False)

    department = relationship("Department", back_populates="subjects")
    enrollments = relationship("Enrollment", back_populates="subject")


class Student(Base):
    __tablename__ = "students"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), unique=True, nullable=False)
    department_id = Column(String(36), ForeignKey("departments.id"), nullable=False)
    section_id = Column(String(36), ForeignKey("sections.id"), nullable=True)
    semester = Column(Integer, default=1, nullable=False)
    roll_number = Column(String(50), unique=True, nullable=False, index=True)
    biometric_status = Column(String(30), default="NOT_REGISTERED", nullable=False)  # NOT_REGISTERED, PENDING_APPROVAL, APPROVED, REJECTED, UPDATE_REQUESTED, SUSPENDED
    biometric_consent_given = Column(Boolean, default=False, nullable=False)
    biometric_consent_at = Column(DateTime(timezone=True), nullable=True)
    non_biometric_exempt = Column(Boolean, default=False, nullable=False)
    accommodation_reason = Column(Text, nullable=True)

    user = relationship("User", back_populates="student_profile")
    department = relationship("Department", back_populates="students")
    enrollments = relationship("Enrollment", back_populates="student")
    face_profile = relationship("FaceProfile", back_populates="student", uselist=False)
    attendance_records = relationship("AttendanceRecord", back_populates="student")


class Teacher(Base):
    __tablename__ = "teachers"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), unique=True, nullable=False)
    department_id = Column(String(36), ForeignKey("departments.id"), nullable=False)
    employee_code = Column(String(50), unique=True, nullable=False, index=True)
    designation = Column(String(100), default="Assistant Professor")

    user = relationship("User", back_populates="teacher_profile")
    department = relationship("Department", back_populates="teachers")
    sessions = relationship("AttendanceSession", back_populates="teacher")


class Enrollment(Base):
    __tablename__ = "enrollments"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    student_id = Column(String(36), ForeignKey("students.id"), nullable=False)
    subject_id = Column(String(36), ForeignKey("subjects.id"), nullable=False)
    semester = Column(Integer, nullable=False)
    academic_year = Column(String(20), nullable=False)

    student = relationship("Student", back_populates="enrollments")
    subject = relationship("Subject", back_populates="enrollments")
    __table_args__ = (UniqueConstraint("student_id", "subject_id", name="uq_student_subject_enrollment"),)


class Timetable(Base):
    __tablename__ = "timetables"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    subject_id = Column(String(36), ForeignKey("subjects.id"), nullable=False)
    section_id = Column(String(36), ForeignKey("sections.id"), nullable=True)
    teacher_id = Column(String(36), ForeignKey("teachers.id"), nullable=False)
    day_of_week = Column(Integer, nullable=False)  # 0=Monday .. 6=Sunday
    start_time = Column(String(5), nullable=False)  # HH:MM (24h UTC/local configured)
    end_time = Column(String(5), nullable=False)    # HH:MM
    room_number = Column(String(50), nullable=False)
    auto_open_offset_minutes = Column(Integer, default=3, nullable=False)
    auto_close_offset_minutes = Column(Integer, default=5, nullable=False)
    qr_refresh_interval = Column(Integer, default=8, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class FaceProfile(Base):
    __tablename__ = "face_profiles"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    student_id = Column(String(36), ForeignKey("students.id"), unique=True, nullable=False)
    encrypted_embedding = Column(LargeBinary, nullable=False)  # AES-256-GCM
    model_version = Column(String(50), default="ArcFace-ResNet100")
    is_active = Column(Boolean, default=True, nullable=False)
    approved_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    student = relationship("Student", back_populates="face_profile")


class FaceRegistrationRequest(Base):
    __tablename__ = "face_registration_requests"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    student_id = Column(String(36), ForeignKey("students.id"), nullable=False)
    request_type = Column(String(20), default="INITIAL", nullable=False)  # INITIAL or UPDATE
    status = Column(String(30), default="PENDING_APPROVAL", nullable=False)  # PENDING_APPROVAL, APPROVED, REJECTED
    orientation_samples_meta = Column(Text, nullable=True)
    encrypted_preview_image = Column(LargeBinary, nullable=True)  # AES-256-GCM encrypted front reference photo for authority review
    candidate_encrypted_embedding = Column(LargeBinary, nullable=True)  # AES-256-GCM encrypted ArcFace embedding when Phase 6 weights active
    embedding_ready = Column(Boolean, default=False, nullable=False)
    reviewed_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    subject_id = Column(String(36), ForeignKey("subjects.id"), nullable=False)
    section_id = Column(String(36), ForeignKey("sections.id"), nullable=True)
    teacher_id = Column(String(36), ForeignKey("teachers.id"), nullable=False)
    timetable_id = Column(String(36), ForeignKey("timetables.id"), nullable=True)
    classroom = Column(String(100), nullable=True)
    geofence_lat = Column(Float, nullable=True)
    geofence_lng = Column(Float, nullable=True)
    geofence_radius_meters = Column(Float, default=150.0, nullable=False)
    geofence_required = Column(Boolean, default=False, nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    mode = Column(String(20), default="MANUAL", nullable=False)  # MANUAL or AUTOMATIC
    status = Column(String(20), default="ACTIVE", nullable=False)  # SCHEDULED, ACTIVE, PAUSED, CLOSED
    qr_refresh_interval = Column(Integer, default=8, nullable=False)  # Seconds (5-10s)
    is_active = Column(Boolean, default=True, nullable=False)
    is_paused = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    teacher = relationship("Teacher", back_populates="sessions")
    records = relationship("AttendanceRecord", back_populates="session")


class VerificationTransaction(Base):
    __tablename__ = "verification_transactions"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    session_id = Column(String(36), ForeignKey("attendance_sessions.id"), nullable=False)
    student_id = Column(String(36), ForeignKey("students.id"), nullable=False)
    qr_nonce = Column(String(64), nullable=False)
    challenges_json = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(30), default="ISSUED", nullable=False)  # ISSUED, LIVENESS_PASSED, COMPLETED, EXPIRED, FAILED
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    session_id = Column(String(36), ForeignKey("attendance_sessions.id"), nullable=False)
    student_id = Column(String(36), ForeignKey("students.id"), nullable=False)
    verification_transaction_id = Column(String(36), ForeignKey("verification_transactions.id"), nullable=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    status = Column(String(20), default="PRESENT", nullable=False)  # PRESENT, LATE, ABSENT, MANUAL_OVERRIDE
    verification_method = Column(String(50), default="QR_LIVENESS_ARCFACE", nullable=False)
    cosine_similarity = Column(Float, nullable=True)
    liveness_score = Column(Float, nullable=True)
    correction_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    session = relationship("AttendanceSession", back_populates="records")
    student = relationship("Student", back_populates="attendance_records")
    __table_args__ = (
        UniqueConstraint("session_id", "student_id", name="uq_session_student_attendance"),
        Index("idx_attendance_student_session", "student_id", "session_id")
    )


class VerificationLog(Base):
    __tablename__ = "verification_logs"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    student_id = Column(String(36), ForeignKey("students.id"), nullable=True)
    session_id = Column(String(36), ForeignKey("attendance_sessions.id"), nullable=True)
    event_type = Column(String(60), nullable=False)
    details = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class LeaveRequest(Base):
    __tablename__ = "leave_requests"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    student_id = Column(String(36), ForeignKey("students.id"), nullable=False)
    subject_id = Column(String(36), ForeignKey("subjects.id"), nullable=True)
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(20), default="PENDING", nullable=False)
    reviewed_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    title = Column(String(150), nullable=False)
    message = Column(Text, nullable=False)
    type = Column(String(30), default="SYSTEM", nullable=False)  # ATTENDANCE_ALERT, BIOMETRIC, SYSTEM
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    action = Column(String(100), nullable=False)
    resource = Column(String(100), nullable=False)
    details = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class InstitutionSetting(Base):
    __tablename__ = "institution_settings"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
