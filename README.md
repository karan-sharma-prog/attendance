# SmartPresence — AI-Powered Secure Attendance Management System

**Full Research Title:** *SmartPresence: An AI-Integrated Attendance Management System Using Secure Dynamic QR Authentication, Facial Liveness Detection and Authority-Verified Biometric Recognition.*

## Key Capabilities
1. **Three-Layer Security Architecture:**
   - **Dynamic QR Authentication:** Server-side HMAC-SHA256 signed QR codes rotating every 5–10 seconds with CSPRNG nonces, TTL validation, and short-lived student verification transactions.
   - **Hybrid AI Facial Liveness:** BlazeFace single-face guard, MediaPipe FaceLandmarker (EAR blink, MAR mouth, SolvePnP 3D head pose), MiniFASNetV2 passive anti-spoofing, static-frame replay detection, and randomized active challenges.
   - **Credential-Based 1:1 Identity Verification:** RetinaFace / SCRFD-10G 5-landmark detection, 112×112 affine alignment, and ArcFace ResNet-100 512-D cosine similarity against AES-256-GCM encrypted authority-approved embeddings.
2. **Operational & Reporting Features:**
   - Role-Based Access Control (Student, Teacher, Administrator) enforced server-side.
   - Teacher manual sessions (2/3/5/10/custom min) + Automatic timetable-linked scheduling.
   - Real-time WebSocket live session roster, Recharts analytics, individual student reports, CSV exports, leave requests, and automated low-attendance (`<75%`) SMTP email alerting.
   - Progressive Web Application (PWA) + Flutter native mobile scaffold with Android `FLAG_SECURE`.

---

## Quick Start (Local Development)

### 1. Environment Setup
Copy `.env.example` to `.env` and populate `DATABASE_URL` (Neon PostgreSQL) and optional `SMTP_USER` / `SMTP_PASSWORD` / `REDIS_URL`.

### 2. Backend Setup
```powershell
python -m venv backend/venv
.\backend\venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\backend\venv\Scripts\python.exe backend/app/ml/download_weights.py
.\backend\venv\Scripts\python.exe backend/init_db.py
.\backend\venv\Scripts\uvicorn.exe backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Frontend Setup (PWA)
```powershell
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173`. For cross-device smartphone camera testing, follow [docs/CROSS_DEVICE_SETUP.md](docs/CROSS_DEVICE_SETUP.md).

### 4. Production Docker Deployment
```bash
docker compose up --build -d
```

### 5. Running Tests
```powershell
.\backend\venv\Scripts\pytest.exe backend/tests/test_ml_models.py -v -s
.\backend\venv\Scripts\pytest.exe backend/tests/test_live_api.py -v
.\backend\venv\Scripts\pytest.exe backend/tests/test_phase8_to_10.py -v -s
```
