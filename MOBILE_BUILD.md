# SmartPresence Mobile Build & Release Guide (Android & iOS)

## 1. Prerequisites

| Tool | Required For | Version |
|---|---|---|
| Node.js & npm | Web bundle + Capacitor CLI | Node 20+ (v24.13 verified) |
| Java JDK | Android Gradle builds | **JDK 17 (Temurin)** |
| Android Studio / Android SDK | Compiling local `.apk` / `.aab` | Android SDK 34+ |
| macOS + Xcode 15+ & CocoaPods | Compiling `.ipa` for iOS | macOS only |

> **Current Host Status:** Node v24.13 and OpenJDK 17.0.17 are installed. Android SDK is **not** installed locally, and this machine runs Windows (so Xcode/iOS compilation is blocked locally). A ready-to-run **GitHub Actions CI workflow** ([`.github/workflows/android-apk.yml`](file:///c:/Users/bhavy/OneDrive/Desktop/smarty/.github/workflows/android-apk.yml)) is included to produce an installable Android Debug APK automatically on GitHub without needing Android Studio locally.

---

## 2. Configure Production Backend URL

Create `frontend/.env.production` (do **not** commit secrets or database credentials):

```env
VITE_API_URL=https://your-deployed-smartpresence.vercel.app/api/v1
```

---

## 3. Build Web Bundle & Sync Capacitor

```bash
cd frontend
npm install
npm run build
npx cap sync
```

---

## 4. Building an Installable Android APK

### Option A — Automated Build via GitHub Actions (No Android Studio Needed)
1. Push your repository to GitHub.
2. Open **Actions → Build SmartPresence Android APK → Run workflow**.
3. Optionally enter your deployed `api_url` (or configure `VITE_API_URL` in GitHub Repository Secrets).
4. Download the **`smartpresence-android-debug-apk`** artifact (`app-debug.apk`) and install it on any Android device.

### Option B — Local Build with Android Studio / Android SDK
1. Install Android Studio and ensure `ANDROID_HOME` is set (e.g., `C:\Users\bhavy\AppData\Local\Android\Sdk`).
2. Build the debug APK via Gradle:
   ```bash
   cd frontend/android
   ./gradlew assembleDebug
   ```
   Output APK: `frontend/android/app/build/outputs/apk/debug/app-debug.apk`
3. Or open in Android Studio:
   ```bash
   npm run mobile:android --prefix frontend
   ```

### Option C — Signed Release APK / Play Store AAB
1. Generate a private upload keystore (keep it **outside** git):
   ```bash
   keytool -genkey -v -keystore smartpresence-release.keystore -alias smartpresence -keyalg RSA -keysize 2048 -validity 10000
   ```
2. Configure signing credentials via local `gradle.properties` (never commit passwords or `.keystore` files):
   ```properties
   SMARTPRESENCE_STORE_FILE=/secure/path/smartpresence-release.keystore
   SMARTPRESENCE_KEY_ALIAS=smartpresence
   SMARTPRESENCE_STORE_PASSWORD=***
   SMARTPRESENCE_KEY_PASSWORD=***
   ```
3. Build Android App Bundle (`.aab`) for Google Play Console:
   ```bash
   cd frontend/android
   ./gradlew bundleRelease
   ```
   Output: `frontend/android/app/build/outputs/bundle/release/app-release.aab`

---

## 5. Building for iOS (Requires macOS + Xcode)

> **Status on Windows:** iOS native compilation is **blocked** because Xcode and CocoaPods require macOS. The Capacitor iOS project (`frontend/ios/`) and `Info.plist` are pre-configured and ready to open on macOS.

On a macOS machine:
```bash
cd frontend
npm ci
npm run build
npx cap sync ios
cd ios/App && pod install
npx cap open ios
```
In Xcode:
1. Select your **Apple Developer Team** under *Signing & Capabilities*.
2. Add **Associated Domains** (`applinks:your-domain.vercel.app`) for Universal Links.
3. Add **Push Notifications** capability.
4. Archive via **Product → Archive** and distribute to TestFlight / App Store Connect.
