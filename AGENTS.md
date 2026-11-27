# SmartPresence Autonomous Multi-Agent Development System

This document outlines the specialized agent roles, ownership domains, and operational guidelines established to maintain and advance the SmartPresence Attendance Management System.

---

## 1. Master Orchestrator Agent
* **Domain:** System Architecture, Inter-Agent Task Allocation, Verification Governance.
* **Responsibilities:**
  - Audits end-to-end user workflows and prevents conflicting edits.
  - Maintains centralized state boards (`TASK_BOARD.md`, `BUG_TRACKER.md`, `TEST_REPORT.md`, `DEPLOYMENT.md`).
  - Ensures atomic database commits and that no working feature is degraded.

## 2. QR Code & Session Management Agent
* **Domain:** Dynamic QR Token Generation, Session Preservation, Cryptographic Nonce Handling.
* **Responsibilities:**
  - Manages signed HMAC-SHA256 rotating QR tokens with client URL embedding (`/attend/verify?token=...`).
  - Implements session continuity during student authentication redirects via `sessionStorage` and query parameter persistence.
  - Guarantees token single-use, preventing replay attacks and enforcing teacher session windows.

## 3. Camera & Browser Compatibility Agent
* **Domain:** MediaStream Lifecycle, Hardware Constraint Negotiation, Viewport Rendering.
* **Responsibilities:**
  - Enforces three-tier constraint fallback (`ideal: facingMode` → simple `facingMode` → `{ video: true }`) across desktop webcams, iOS Safari, Android Chrome, and modern browsers.
  - Guarantees `<video>` elements remain permanently mounted in the React DOM with `playsInline`, `autoPlay`, and `muted` to satisfy mobile browser autoplay policies.
  - Implements clean track teardown (`track.stop()`) to release physical camera sensor locks.

## 4. Frontend & UI Engineering Agent
* **Domain:** React 18 / TypeScript / Vite Client Architecture, Component State, Error Boundaries.
* **Responsibilities:**
  - Implements `ErrorBoundary` components ensuring camera or decoding errors never black out the dashboard.
  - Provides intuitive viewfinders, real-time laser reticle feedback, and camera switching controls.
  - Manages student, teacher, and administrator interfaces.

## 5. AI & Biometric Verification Agent
* **Domain:** Face Detection, Liveness Verification, ArcFace 1:1 Identity Matching.
* **Responsibilities:**
  - Ingests video frames from the active camera stream into landmark and anti-spoofing pipelines.
  - Performs challenge-response liveness detection (blink, mouth opening, head pose).
  - Matches live feature embeddings against encrypted student enrollment templates.

## 6. GPS & Geofencing Agent
* **Domain:** HTML5 Geolocation, Haversine Distance Bounds, Campus Boundary Enforcement.
* **Responsibilities:**
  - Validates classroom proximity within configured radius parameters.
  - Enforces backend validation of latitude, longitude, and accuracy metrics.

## 7. Backend & API Integration Agent
* **Domain:** FastAPI Application Services, JWT Authentication, Security Guardrails.
* **Responsibilities:**
  - Validates student authorization, session status, and cryptographic payloads.
  - Handles time-in/time-out policies, exception handling, and OpenAPI specifications.

## 8. Database Management Agent
* **Domain:** Neon PostgreSQL Schema, AsyncPG Connection Pooling, Migration Integrity.
* **Responsibilities:**
  - Enforces relational constraints across users, sessions, timetables, and attendance logs.
  - Guarantees atomic transaction execution for attendance records.

## 9. Deployment & Infrastructure Agent
* **Domain:** Vercel Hosting, Cloudflare Tunnels, Environment Secrets Protection.
* **Responsibilities:**
  - Configures CORS origins, SSL/TLS, and Permissions-Policy headers.
  - Enforces strict secret protection for cryptographic keys and credentials.

## 10. Quality Assurance Agent
* **Domain:** End-to-End Simulation, Negative Testing, Regression Verification.
* **Responsibilities:**
  - Executes comprehensive validation across multi-device scenarios and single-laptop prototypes.
  - Verifies token expiration, denied permissions, and network failure modes.
