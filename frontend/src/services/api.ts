import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_URL || '/api/v1';

export const api = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Keep tokens in memory + sessionStorage (never store biometric data or QR secrets in localStorage)
let accessToken: string | null = sessionStorage.getItem('sp_access_token');
let refreshToken: string | null = sessionStorage.getItem('sp_refresh_token');

export function setAuthTokens(access: string | null, refresh: string | null) {
  accessToken = access;
  refreshToken = refresh;
  if (access) sessionStorage.setItem('sp_access_token', access);
  else sessionStorage.removeItem('sp_access_token');

  if (refresh) sessionStorage.setItem('sp_refresh_token', refresh);
  else sessionStorage.removeItem('sp_refresh_token');
}

export function getAccessToken(): string | null {
  return accessToken;
}

api.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && refreshToken && !original._retry && !original.url?.includes('/auth/login')) {
      original._retry = true;
      try {
        const res = await axios.post(`${API_BASE}/auth/refresh`, { refresh_token: refreshToken });
        setAuthTokens(res.data.access_token, res.data.refresh_token);
        original.headers.Authorization = `Bearer ${res.data.access_token}`;
        return api(original);
      } catch {
        setAuthTokens(null, null);
      }
    }
    return Promise.reject(error);
  }
);

export interface AuthUser {
  user_id: string;
  email: string;
  full_name: string;
  role: 'student' | 'teacher' | 'admin';
  student_id?: string | null;
  teacher_id?: string | null;
  enrollment_id?: string | null;
}

export interface SubjectItem {
  id: string;
  code: string;
  name: string;
  credits: number;
}

export interface SessionSummary {
  id: string;
  subject_id: string;
  subject_code: string;
  subject_name: string;
  teacher_name: string;
  classroom: string | null;
  start_time: string;
  end_time: string;
  mode: string;
  status: string;
  qr_refresh_interval: number;
  is_active: boolean;
  is_paused: boolean;
  geofence_required?: boolean;
  geofence_lat?: number | null;
  geofence_lng?: number | null;
  geofence_radius_meters?: number;
  enrolled_count: number;
  present_count: number;
  pending_count: number;
  absent_count: number;
  server_time: string;
}

export interface DynamicQRResponse {
  session_id: string;
  qr_url: string;
  qr_token: string;
  qr_image_data_url: string;
  issued_at: number;
  expires_at: number;
  refresh_interval: number;
  session_end_time: string;
  server_time: string;
}

export interface StudentInSessionItem {
  student_id: string;
  full_name: string;
  roll_number: string;
  email: string;
  status: string;
  marked_at: string | null;
  verification_method: string | null;
}

export interface SessionDetailResponse extends SessionSummary {
  students: StudentInSessionItem[];
}

export interface TimetableResponse {
  id: string;
  subject_id: string;
  subject_code: string;
  subject_name: string;
  department_code: string;
  teacher_id: string;
  teacher_name: string;
  day_of_week: number;
  start_time: string;
  end_time: string;
  room_number: string;
  auto_open_offset_minutes: number;
  auto_close_offset_minutes: number;
  qr_refresh_interval: number;
  is_active: boolean;
  matched_student_count: number;
}

export interface VerificationInitResponse {
  transaction_id: string;
  student_id: string;
  session_id: string;
  subject_code: string;
  subject_name: string;
  expires_at: string;
  active_challenges: string[];
  geofence_required: boolean;
  geofence_radius_meters: number;
  next_stage: string;
}

export interface StudentAttendanceReportItem {
  subject_id: string;
  subject_code: string;
  subject_name: string;
  total_classes: number;
  attended_classes: number;
  attendance_percentage: number;
  is_at_risk: boolean;
}

export interface IndividualStudentReportResponse {
  student_id: string;
  student_name: string;
  roll_number: string;
  enrollment_id: string;
  department: string;
  overall_percentage: number;
  is_overall_at_risk: boolean;
  courses: StudentAttendanceReportItem[];
}

export interface LowAttendanceStudentItem {
  student_id: string;
  student_name: string;
  roll_number: string;
  email: string;
  subject_name: string;
  attended_classes: number;
  total_classes: number;
  attendance_percentage: number;
}
