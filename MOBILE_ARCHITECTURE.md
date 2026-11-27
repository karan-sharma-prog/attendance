# SmartPresence Mobile Application Architecture

SmartPresence uses a **shared React 18 + TypeScript + Vite + Capacitor 6 codebase** that builds both the existing Vercel web application and native Android & iOS mobile applications without duplicating business logic.

---

## 1. Platform Abstraction Layer (`frontend/src/services/`)

| Service | Native Behavior (Android / iOS) | Web Behavior (Browser / Vercel) |
|---|---|---|
| [`platformService.ts`](file:///c:/Users/bhavy/OneDrive/Desktop/smarty/frontend/src/services/platformService.ts) | Detects `Capacitor.isNativePlatform()`, styles StatusBar & hides SplashScreen. | No-ops native shell hooks cleanly. |
| [`secureStorageService.ts`](file:///c:/Users/bhavy/OneDrive/Desktop/smarty/frontend/src/services/secureStorageService.ts) | Stores JWT access/refresh tokens in **Android Keystore / iOS Keychain** via `capacitor-secure-storage-plugin` (never plain Preferences). | Uses `sessionStorage` (never `localStorage`). |
| [`cameraService.ts`](file:///c:/Users/bhavy/OneDrive/Desktop/smarty/frontend/src/services/cameraService.ts) | Centralized MediaStream coordinator: guarantees QR rear camera is **always stopped** before facial front camera initializes; 3-tier constraint fallback (`ideal` → `facingMode` → `{ video: true }`). | Same unified service supporting laptop webcams & mobile browsers. |
| [`geolocationService.ts`](file:///c:/Users/bhavy/OneDrive/Desktop/smarty/frontend/src/services/geolocationService.ts) | Uses `@capacitor/geolocation` with runtime permission prompts. | Falls back to HTML5 `navigator.geolocation`. |
| [`deepLinkService.ts`](file:///c:/Users/bhavy/OneDrive/Desktop/smarty/frontend/src/services/deepLinkService.ts) | Listens for `smartpresence://attend/verify?token=...` and HTTPS App Links via `@capacitor/app`, persisting pending tokens through login. | Reads `window.location.search` `?token=...` on load. |
| [`pushNotificationService.ts`](file:///c:/Users/bhavy/OneDrive/Desktop/smarty/frontend/src/services/pushNotificationService.ts) | Registers native push notifications via `@capacitor/push-notifications`. | Gracefully no-ops; uses in-app notification polling. |
| [`api.ts`](file:///c:/Users/bhavy/OneDrive/Desktop/smarty/frontend/src/services/api.ts) | Targets production HTTPS backend (`VITE_API_URL`) instead of relative proxy paths. | Uses `/api/v1` proxy (Vite dev / Vercel routes) or `VITE_API_URL`. |

---

## 2. Camera Lifecycle & Security Guarantees

1. **Single-Owner Hardware Lock:** `acquireCameraStream()` always calls `stopGlobalCameraStream()` and yields `120ms` so mobile camera sensors fully release before switching from Rear (QR) to Front (Face).
2. **WebView Rendering Compliance:** Both `QrScannerView.tsx` and `FacialVerificationFlow.tsx` keep `<video>` permanently mounted in the DOM and toggle visibility via `opacity-0` / `opacity-100` (never `display: none`), preventing Android WebView / iOS WKWebView frame decoding stalls.
3. **No Biometric Bypasses:** Removed the legacy *"Continue without camera"* bypass in `FacialVerificationFlow.tsx`. All biometric liveness (8-frame temporal analysis) and 1:1 ArcFace checks execute server-side on FastAPI.
4. **GPS Spoofing Limitations:** Browser and Capacitor Geolocation rely on OS-reported coordinates (`latitude`, `longitude`, `accuracy_meters`). Server-side Haversine geofencing validates classroom proximity, but determined users with rooted/mock-location devices can spoof OS GPS; combining GPS with rotating HMAC QR + live biometric liveness mitigates remote proxy attendance.

---

## 3. Native Configurations

* **Capacitor Config:** [`frontend/capacitor.config.ts`](file:///c:/Users/bhavy/OneDrive/Desktop/smarty/frontend/capacitor.config.ts) (`appId: edu.smartpresence.app`, HTTPS Android scheme, Dark splash screen & status bar).
* **Android Manifest:** [`frontend/android/app/src/main/AndroidManifest.xml`](file:///c:/Users/bhavy/OneDrive/Desktop/smarty/frontend/android/app/src/main/AndroidManifest.xml) (Camera, Flashlight, Fine/Coarse GPS, Notifications, Custom Scheme & HTTPS App Links).
* **Android MainActivity:** [`frontend/android/app/src/main/java/edu/smartpresence/app/MainActivity.java`](file:///c:/Users/bhavy/OneDrive/Desktop/smarty/frontend/android/app/src/main/java/edu/smartpresence/app/MainActivity.java) (`setMediaPlaybackRequiresUserGesture(false)` + runtime `CAMERA` permission request).
* **iOS Info.plist:** [`frontend/ios/App/App/Info.plist`](file:///c:/Users/bhavy/OneDrive/Desktop/smarty/frontend/ios/App/App/Info.plist) (`NSCameraUsageDescription`, `NSLocationWhenInUseUsageDescription`, `NSFaceIDUsageDescription`, `smartpresence://` URL scheme).
* **Backend CORS:** [`backend/app/core/config.py`](file:///c:/Users/bhavy/OneDrive/Desktop/smarty/backend/app/core/config.py) automatically permits `capacitor://localhost`, `https://localhost`, and `http://localhost`.
