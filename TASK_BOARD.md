# SmartPresence Centralized Task Board

| Task ID | Component | Description | Owner Agent | Status |
|---|---|---|---|---|
| **SP-001** | Backend | Resolve FastAPI service startup and Neon PostgreSQL pooling connection | Backend / Database | **COMPLETED** |
| **SP-002** | Frontend | Fix QR Scanner camera active but black screen issue with direct video element | Camera / Frontend | **COMPLETED** |
| **SP-003** | Frontend | Implement React ErrorBoundary to prevent portal blackouts on camera errors | Frontend | **COMPLETED** |
| **SP-004** | Camera / Biometrics | Unify `cameraService.ts` (QR → Face hardware release), fix `display: none` WebView bug, remove insecure camera bypass | Native Camera & AI | **COMPLETED** |
| **SP-005** | Mobile Core | Integrate Capacitor 6, Android & iOS projects, and platform abstraction services | Mobile Architecture | **COMPLETED** |
| **SP-006** | Mobile Security | Integrate Keystore/Keychain secure token storage (`capacitor-secure-storage-plugin`) & Capacitor CORS origins | Auth & Backend | **COMPLETED** |
| **SP-007** | Mobile Native | Integrate Capacitor Geolocation, Deep Links (`smartpresence://` + App Links), Flashlight toggle, Push Notifications | Native QR / GPS / Push | **COMPLETED** |
| **SP-008** | Mobile UI/UX | Add mobile bottom navigation bar, safe-area inset support, and Dark/Light theme switcher | Mobile UI/UX | **COMPLETED** |
| **SP-009** | Android Build | Configure `AndroidManifest.xml`, `MainActivity.java`, and GitHub Actions APK pipeline (local SDK absent) | Android Build | **COMPLETED (CI Ready)** |
| **SP-010** | iOS Build | Generate & configure Capacitor `ios/` project and `Info.plist` (compilation blocked on Windows host) | iOS Build | **CONFIGURED (Xcode Blocked)** |
| **SP-011** | Docs & QA | Execute build/sync verification and update `MOBILE_ARCHITECTURE.md`, `MOBILE_BUILD.md`, `TEST_REPORT.md` | QA & Deployment | **COMPLETED** |
