from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime


# Auth Schemas
class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    user_id: str
    email: str
    full_name: str
    student_id: Optional[str] = None
    teacher_id: Optional[str] = None


class LoginRequest(BaseModel):
    identifier: str  # Email or Enrollment ID
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


class UserCreate(BaseModel):
    email: EmailStr
    enrollment_id: Optional[str] = None
    password: str
    full_name: str
    role: str  # student, teacher, admin
    department_code: str
    roll_number: Optional[str] = None
    employee_code: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    email: str
    enrollment_id: Optional[str]
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    student_id: Optional[str] = None
    teacher_id: Optional[str] = None


# Timetable & Subject Schemas
class SubjectItem(BaseModel):
    id: str
    code: str
    name: str
    credits: int


class TimetableCreate(BaseModel):
    subject_code: str
    day_of_week: int = Field(..., ge=0, le=6)
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    room_number: str
    auto_open_offset_minutes: int = Field(default=3, ge=0, le=30)
    auto_close_offset_minutes: int = Field(default=5, ge=1, le=60)
    qr_refresh_interval: int = Field(default=8, ge=5, le=10)


class TimetableResponse(BaseModel):
    id: str
    subject_id: str
    subject_code: str
    subject_name: str
    department_code: str = "CSE"
    teacher_id: str
    teacher_name: str = "Faculty"
    day_of_week: int
    start_time: str
    end_time: str
    room_number: str
    auto_open_offset_minutes: int
    auto_close_offset_minutes: int
    qr_refresh_interval: int
    is_active: bool
    matched_student_count: int = 0


class TimetableCsvUploadRequest(BaseModel):
    csv_content: str
    replace_existing: bool = False
    auto_enroll_department_students: bool = True


class TimetableUploadResult(BaseModel):
    created_count: int
    matched_students_enrolled: int
    errors: List[str]
    timetables: List[TimetableResponse]


# Attendance Session & QR Schemas
class SessionCreate(BaseModel):
    subject_code: str
    duration_minutes: int = Field(default=5, ge=1, le=180)
    mode: str = Field(default="MANUAL")  # MANUAL or AUTOMATIC
    qr_refresh_interval: int = Field(default=8, ge=5, le=10)
    classroom: Optional[str] = "Hall 302"
    scheduled_start_iso: Optional[datetime] = None
    geofence_required: bool = False
    geofence_lat: Optional[float] = None
    geofence_lng: Optional[float] = None
    geofence_radius_meters: float = Field(default=150.0, ge=10.0, le=5000.0)


class SessionExtendRequest(BaseModel):
    additional_minutes: int = Field(..., ge=1, le=60)


class SessionSummary(BaseModel):
    id: str
    subject_id: str
    subject_code: str
    subject_name: str
    teacher_name: str
    classroom: Optional[str]
    start_time: datetime
    end_time: datetime
    mode: str
    status: str
    qr_refresh_interval: int
    is_active: bool
    is_paused: bool
    geofence_required: bool = False
    geofence_lat: Optional[float] = None
    geofence_lng: Optional[float] = None
    geofence_radius_meters: float = 150.0
    enrolled_count: int
    present_count: int
    pending_count: int
    absent_count: int
    server_time: datetime


class DynamicQRResponse(BaseModel):
    session_id: str
    qr_url: str
    qr_token: str
    qr_image_data_url: str
    issued_at: int
    expires_at: int
    refresh_interval: int
    session_end_time: datetime
    server_time: datetime


class StudentInSessionItem(BaseModel):
    student_id: str
    full_name: str
    roll_number: str
    email: str
    status: str  # PRESENT, PENDING_VERIFICATION, ABSENT, MANUAL_OVERRIDE
    marked_at: Optional[datetime] = None
    verification_method: Optional[str] = None


class SessionDetailResponse(SessionSummary):
    students: List[StudentInSessionItem]


# QR Scan & Verification Transaction Schemas
class VerificationInitRequest(BaseModel):
    qr_token: str


class VerificationInitResponse(BaseModel):
    transaction_id: str
    student_id: str
    session_id: str
    subject_code: str
    subject_name: str
    expires_at: datetime
    active_challenges: List[str]
    geofence_required: bool = False
    geofence_radius_meters: float = 150.0
    next_stage: str


class GeofenceVerifyRequest(BaseModel):
    transaction_id: str
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    accuracy_meters: Optional[float] = None


class GeofenceVerifyResponse(BaseModel):
    transaction_id: str
    geofence_verified: bool
    distance_meters: float
    allowed_radius_meters: float
    detail: str


# Reports & Alerting Schemas
class StudentAttendanceReportItem(BaseModel):
    subject_id: str
    subject_code: str
    subject_name: str
    total_classes: int
    attended_classes: int
    attendance_percentage: float
    is_at_risk: bool


class IndividualStudentReportResponse(BaseModel):
    student_id: str
    student_name: str
    roll_number: str
    enrollment_id: str
    department: str
    overall_percentage: float
    is_overall_at_risk: bool
    courses: List[StudentAttendanceReportItem]


class LowAttendanceStudentItem(BaseModel):
    student_id: str
    student_name: str
    roll_number: str
    email: str
    subject_name: str
    attended_classes: int
    total_classes: int
    attendance_percentage: float


class LowAttendanceEmailRequest(BaseModel):
    student_ids: Optional[List[str]] = None
    subject_id: Optional[str] = None
    threshold: float = 75.0
    custom_message: Optional[str] = None


# Phase 5: Biometric Enrollment & Authority Approval Schemas
class BiometricConsentRequest(BaseModel):
    consent_accepted: bool


class FrameValidationRequest(BaseModel):
    orientation: str = Field(..., pattern="^(front|left|right|up|down)$")
    image_base64: str


class FrameQualityResult(BaseModel):
    passed: bool
    orientation: str
    width: int
    height: int
    brightness: float
    contrast: float
    sharpness: float
    face_count: Optional[int] = None
    detector_mode: str
    reasons: List[str]


class BiometricOrientationCapture(BaseModel):
    orientation: str = Field(..., pattern="^(front|left|right|up|down)$")
    image_base64: str


class BiometricRegisterRequest(BaseModel):
    consent_accepted: bool
    samples: List[BiometricOrientationCapture] = Field(..., min_length=5, max_length=5)


class BiometricStatusResponse(BaseModel):
    student_id: str
    biometric_status: str  # NOT_REGISTERED, PENDING_APPROVAL, APPROVED, REJECTED, UPDATE_REQUESTED, SUSPENDED
    biometric_consent_given: bool
    biometric_consent_at: Optional[datetime] = None
    non_biometric_exempt: bool
    accommodation_reason: Optional[str] = None
    latest_request_id: Optional[str] = None
    latest_request_status: Optional[str] = None
    latest_rejection_reason: Optional[str] = None
    embedding_ready: bool
    ml_readiness: dict


class AdminBiometricRequestItem(BaseModel):
    request_id: str
    student_id: str
    student_name: str
    roll_number: str
    email: str
    department: str
    semester: int
    request_type: str
    status: str
    student_biometric_status: str
    embedding_ready: bool
    orientation_metrics: Optional[dict] = None
    rejection_reason: Optional[str] = None
    created_at: datetime


class AdminApproveBiometricRequest(BaseModel):
    request_id: str
    grant_non_biometric_alternative: bool = False
    accommodation_reason: Optional[str] = None


class AdminRejectBiometricRequest(BaseModel):
    request_id: str
    rejection_reason: str = Field(..., min_length=5, max_length=500)


class AdminSuspendBiometricRequest(BaseModel):
    student_id: str
    reason: str = Field(..., min_length=5, max_length=500)


# Phase 7: Liveness, 1:1 Identity & Atomic Attendance Decision Schemas
class ChallengeRefreshRequest(BaseModel):
    transaction_id: str
    accessible_mode: bool = False


class LivenessVerifyRequest(BaseModel):
    transaction_id: str
    frames_base64: List[str] = Field(..., min_length=3, max_length=12)


class LivenessVerifyResponse(BaseModel):
    transaction_id: str
    liveness_verified: bool
    passive_live_score: float
    challenge_results: dict
    telemetry: dict
    next_stage: str
    detail: str


class IdentityVerifyRequest(BaseModel):
    transaction_id: str
    image_base64: str


class IdentityVerifyResponse(BaseModel):
    transaction_id: str
    face_matched: bool
    similarity_score: float
    threshold: float
    next_stage: str
    detail: str


class CompleteVerificationRequest(BaseModel):
    transaction_id: str


class CompleteVerificationResponse(BaseModel):
    attendance_record_id: str
    session_id: str
    subject_code: str
    subject_name: str
    status: str
    marked_at: datetime
    verification_method: str
    liveness_score: Optional[float] = None
    cosine_similarity: Optional[float] = None


class AttendanceCorrectionRequest(BaseModel):
    session_id: str
    student_id: str
    status: str = Field(..., pattern="^(PRESENT|LATE|ABSENT|MANUAL_OVERRIDE)$")
    correction_reason: str = Field(..., min_length=5, max_length=255)


class AttendanceRecordItem(BaseModel):
    id: str
    session_id: str
    subject_code: str
    subject_name: str
    timestamp: datetime
    status: str
    verification_method: str
    liveness_score: Optional[float] = None
    cosine_similarity: Optional[float] = None
    correction_reason: Optional[str] = None


