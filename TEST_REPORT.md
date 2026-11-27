# SmartPresence End-to-End & Mobile Verification Test Report

## Test Summary
* **Date:** 2026-11-27
* **Host Environment:** Windows, Node.js `v24.13.0`, npm `11.6.2`, OpenJDK `17.0.17`, Python 3.12, Neon PostgreSQL
* **Build Status:** **WEB + CAPACITOR SYNC PASSED (0 ERRORS)**
* **Native Compilation Status:** Android APK local Gradle compile blocked (Android SDK not installed locally; CI workflow ready). iOS compilation blocked (macOS/Xcode unavailable).

---

### Executed Tests & Actual Results

| # | Test Case | Command / Method | Expected Result | Actual Result | Status |
|---|---|---|---|---|---|
| 1 | Backend Health Check | `GET http://127.0.0.1:8000/health` | HTTP 200 `HEALTHY` | HTTP 200 `{"status":"HEALTHY","app":"SmartPresence","version":"1.0.0"}` | **PASSED** |
| 2 | Student Auth via Vite Proxy | `POST http://127.0.0.1:5173/api/v1/auth/login` | HTTP 200 + JWT tokens | HTTP 200 with valid Argon2id-verified `access_token` & `refresh_token` | **PASSED** |
| 3 | Neon PostgreSQL Connectivity | AsyncPG `SELECT 1` | Returns `1` | Returned `DB SUCCESS: 1` | **PASSED** |
| 4 | TypeScript & Vite Production Build | `npm run build --prefix frontend` | 0 TS errors, bundle in `dist/` | 0 errors; 2221 modules transformed in 6.61s | **PASSED** |
| 5 | Capacitor Android & iOS Project Sync | `npx cap add android` & `npx cap add ios` + `npx cap sync` | 7 plugins linked on both platforms | All 7 plugins linked (`app`, `geolocation`, `network`, `push-notifications`, `splash-screen`, `status-bar`, `capacitor-secure-storage-plugin`) | **PASSED** |
| 6 | Backend CORS Native Origins | Inspect `backend/app/core/config.py` | Permits `capacitor://localhost`, `https://localhost`, `http://localhost` | Validator appends all 3 native origins automatically | **PASSED** |
| 7 | Local Android APK Compilation | `./gradlew assembleDebug` | Produces `app-debug.apk` | **BLOCKED LOCALLY:** `ANDROID_HOME` / Android SDK not installed on host. Mitigated via `.github/workflows/android-apk.yml`. | **BLOCKED (Local SDK)** |
| 8 | Local iOS `.ipa` Compilation | `xcodebuild` / CocoaPods | Produces iOS archive | **BLOCKED:** Host OS is Windows; Xcode/macOS required. `frontend/ios/` project & `Info.plist` are configured. | **BLOCKED (No macOS)** |
| 9 | Physical Android/iOS Device Camera & Liveness Test | Physical mobile hardware test | Rear QR -> Front Face -> GPS -> Neon DB | **NOT EXECUTED** (requires installing the built APK on a physical Android phone or running on a physical device). | **PENDING DEVICE** |
