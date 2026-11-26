# SmartPresence — Development Status & Tracking

**Project Title:** SmartPresence: An AI-Integrated Attendance Management System Using Secure Dynamic QR Authentication, Facial Liveness Detection and Authority-Verified Biometric Recognition.

**Current Status:** Phases 0–10 Implemented & Verified (Automated Backend, ML, Neon PostgreSQL, and PWA Build Suites Passing).

---

## 1. Completed Modules (Phases 0–10)
- **Phase 0–2 (Foundation, Neon PostgreSQL & Auth):** 19 relational tables on Neon PostgreSQL, Argon2id password hashing, JWT access + rotating refresh tokens, logout JTI revocation, and server-side RBAC (`require_roles`).
- **Phase 3 (Attendance Sessions & Timetable):** Manual (`2/3/5/10/custom` min) & automatic timetable-linked sessions, overlap protection, pause/resume/extend/close controls, and server-UTC window enforcement.
- **Phase 4 (Dynamic QR & Real-Time Monitor):** HMAC-SHA256 dynamic QR codes rotating every 5–10s, shared QR multi-student scanning, 150s student-specific `VerificationTransaction`, and JWT-protected `/ws/attendance/{session_id}`.
- **Phase 5 (Biometric Enrollment & Authority Approval):** 5-orientation front-camera capture, OpenCV quality gate, AES-256-GCM encrypted embeddings/previews, consent/deletion controls, non-biometric accommodation flag, and Admin review console.
- **Phase 6 (Hybrid ML Integration):** Verified weights & standalone inference modules for BlazeFace, MediaPipe FaceLandmarker (EAR, MAR, SolvePnP), RetinaFace/SCRFD-10G, MiniFASNetV2, and ArcFace ResNet-100.
- **Phase 7 (End-to-End Attendance Pipeline):** Multi-frame liveness (`/verification/liveness` with static-replay guard + MiniFASNetV2 + temporal challenge-response), 1:1 ArcFace cosine verification (`/verification/identity`), server-side rule-based decision engine (`/verification/complete`), atomic duplicate-safe `AttendanceRecord`, and auditable manual corrections (`/attendance/correction`).
- **Phase 8 (Analytics, Reports, Leave, Notifications & Mailer):** Recharts analytics dashboard, security alerts & audit logs, individual student attendance reports, CSV export (`/attendance/export`), low-attendance warning emailer (`/reports/send-low-attendance-emails`), leave request workflow (`/leave/...`), notifications (`/notifications`), and Admin Console (`/admin/overview`, `/admin/subjects`, `/admin/users`, `/admin/settings`).
- **Phase 9 (PWA & Native Mobile Scaffold):** Installable PWA (`manifest.json`, `sw.js` static shell cache—never caching APIs/QR/biometrics, offline indicator, install button) + Flutter app scaffold (`mobile_flutter/`) with Google ML Kit `mobile_scanner` and Android `FLAG_SECURE` `MethodChannel`.
- **Phase 10 (Testing, Security, Load Benchmarks & Deployment):** Multi-stage Dockerfiles, `docker-compose.yml`, `nginx.conf`, architecture/ER/security documentation (`docs/ARCHITECTURE_AND_SECURITY.md`), and `README.md`.
- **Dynamic HTTPS QR, Mobile Front-Camera Fix & CSE Timetable Sync:** Complete HTTPS `/verify?token=...` QR URL routing with pending verification preservation across login, persistent `<video>` + `onPlaying` readiness fix for mobile front cameras during liveness/enrollment, and Teacher CSV/manual timetable upload with automatic CSE department student schedule matching.

---

## 2. Verified Test & Build Results

| Suite / Command | Scope | Measured Result |
|---|---|---|
| `npm run build` | TypeScript + Vite PWA bundle (`tsc && vite build`) | **PASSED** (`✓ built in 8.28s`, exit code 0) |
| `pytest backend/tests/test_phase8_to_10.py -v` | Analytics, Leave/Notifications, Admin, Load Benchmark & Timetable CSV/CSE Matching | **3 PASSED in 137.58s** |
| `pytest backend/tests/test_ml_models.py -v -s` *(prior phase run)* | Standalone inference on all 5 core ML models | **6 PASSED in 7.67s** (BlazeFace 71.9 ms, FaceLandmarker 37.6 ms, RetinaFace 132.1 ms, MiniFASNetV2 77.2 ms [0.9996 live vs 0.0131 spoof], ArcFace 1667.1 ms [0.9993 genuine vs 0.0417 impostor]) |
| `pytest backend/tests/test_live_api.py -v` *(prior phase run)* | Auth/RBAC, Session/QR lifecycle, Reports/Mailer, Biometrics & Phase 7 e2e | **7 PASSED**; Phase 7 e2e (`test_phase7_complete_attendance_pipeline_e2e`) **PASSED in 124.85s** |

---

## 3. Unverified Items, Security Limitations & Remaining User Actions
- **Physical Smartphone Cross-Device Test:** Not yet executed on physical laptop + Android/iPhone hardware (requires HTTPS tunnel or `adb reverse`; see `docs/CROSS_DEVICE_SETUP.md`).
- **Native Flutter Compilation (`mobile_flutter/`):** Flutter SDK is not installed in PATH on this Windows machine, so `flutter test` / `flutter build` has not been run locally.
- **Docker Build (`docker compose up`):** Docker is not installed in PATH on this machine, so container builds are unverified locally.
- **SMTP Live Delivery & Redis Daemon:** `SMTP_USER` / `SMTP_PASSWORD` are unset (warning emails log instead of sending via SMTP), and `REDIS_URL` uses the in-process TTL fallback (`redis_connected: false`).
- **Multi-Subject ML Threshold Calibration:** ArcFace & MiniFASNet thresholds were verified on individual reference images; full ROC-AUC / EER / APCER / BPCER across demographics and lighting requires a consented multi-subject validation dataset.
- **Browser Screenshot Limitation:** Browser Projection Mode hides copy buttons and rotates QRs every 5–10s, but web browsers cannot block external cameras or OS screenshots.
