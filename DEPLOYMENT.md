# SmartPresence Deployment Architecture & Configuration

## Architecture Overview
* **Frontend:** React 18 SPA built with Vite and Tailwind CSS.
* **Backend:** FastAPI with AsyncPG connection pooling.
* **Database:** Serverless Neon PostgreSQL (AWS us-east-2).
* **Caching & Nonces:** Redis with automatic fallback to in-memory TTL store.

## Environment Configuration
```env
# Server Binding
HOST=0.0.0.0
PORT=8000

# Security & Tokens
SECRET_KEY=<SECURE_KEY>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# Database Connection (Neon PostgreSQL)
DATABASE_URL=postgresql+asyncpg://<USER>:<PASS>@<HOST>/neondb?sslmode=require
DATABASE_URL_SYNC=postgresql://<USER>:<PASS>@<HOST>/neondb?sslmode=require

# AI & Verification Thresholds
ARCFACE_SIMILARITY_THRESHOLD=0.68
MINIFASNET_LIVENESS_THRESHOLD=0.85
BLINK_EAR_THRESHOLD=0.22
MOUTH_MAR_THRESHOLD=0.55
```

## Security & Deployment Guidelines
1. **Camera Permissions:** Ensure production domain serves exclusively over HTTPS. Modern mobile browsers block `navigator.mediaDevices.getUserMedia` on plain HTTP (except `localhost`).
2. **Permissions Policy:** Include `camera=(self), geolocation=(self)` in deployment headers.
3. **Database Credentials:** Stored strictly in environment secrets; never committed to version control.
