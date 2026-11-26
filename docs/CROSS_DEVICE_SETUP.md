# SmartPresence — Cross-Device LAN & HTTPS Setup Guide

To test real cross-device QR scanning (Teacher dashboard on a laptop + Student smartphone scanning with its rear camera):

## 1. Network & Binding Requirements
- Both the development laptop and the student smartphone must be on the **same Wi-Fi / LAN network** (and client isolation / AP isolation must be disabled on the router).
- The FastAPI backend binds to `0.0.0.0:8000` (configured via `HOST=0.0.0.0` in `.env`).
- The Vite frontend binds to `0.0.0.0:5173` (configured in `frontend/vite.config.ts`) and proxies `/api` and `/ws` directly to `http://127.0.0.1:8000`, avoiding hardcoded `localhost` calls from smartphones.

## 2. Find Your Laptop's LAN IPv4 Address (Windows)
Run in PowerShell:
```powershell
ipconfig | findstr /i "IPv4"
```
Example output: `IPv4 Address. . . . . . . . . . . : 192.168.1.42`

Add `http://192.168.1.42:5173` (or `https://...`) to `CORS_ORIGINS` in `.env` if accessing the backend directly without the Vite proxy.

## 3. Windows Firewall Rules (Allow Ports 5173 & 8000 on Private Network)
Run in an elevated PowerShell prompt if your phone cannot reach the laptop:
```powershell
New-NetFirewallRule -DisplayName "SmartPresence Vite 5173" -Direction Inbound -Protocol TCP -LocalPort 5173 -Action Allow -Profile Private
New-NetFirewallRule -DisplayName "SmartPresence FastAPI 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private
```

## 4. Trusted HTTPS for Smartphone Camera Access (`MediaDevices.getUserMedia`)
Modern mobile browsers (Chrome on Android, Safari on iOS) **block `navigator.mediaDevices.getUserMedia` on plain `http://<LAN_IP>`** (only `https://` or `http://localhost` is considered a secure context).

To enable rear & front camera access on a physical smartphone during local development, use one of:
1. **mkcert + Vite HTTPS** (local trusted CA installed on laptop and phone), OR
2. **An HTTPS tunnel** (e.g., Cloudflare Tunnel `cloudflared tunnel --url http://localhost:5173` or `ngrok http 5173`), OR
3. **Android USB Port Forwarding (`adb reverse`)**: Connect Android via USB with USB Debugging enabled and run:
   ```powershell
   adb reverse tcp:5173 tcp:5173
   ```
   Then open `http://localhost:5173` directly on the Android phone's Chrome browser (which is treated as a secure context for camera access).

## 5. Starting Both Servers Locally
**Terminal 1 (Backend FastAPI):**
```powershell
.\backend\venv\Scripts\uvicorn.exe backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```
**Terminal 2 (Frontend Vite):**
```powershell
cd frontend
npm run dev
```
