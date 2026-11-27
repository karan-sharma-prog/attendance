# SmartPresence Bug Tracker & Resolution Log

## Bug SP-BUG-01: Rear Camera Scanner Screen Pitch Black
- **Severity:** Critical (Blocks student QR attendance flow)
- **Reported Behavior:** When clicking "Open Rear Camera Scanner", physical camera LED turns on, but viewport is completely black.
- **Root Cause Analysis:**
  1. `html5-qrcode` was dynamically injecting video elements into a container that was conditionally unmounted/mutated by React during state transitions (`!scanning && ...`), detaching DOM nodes while the stream was playing.
  2. The injected video element lacked explicit height rules under Tailwind CSS preflight (`max-width: 100%; height: auto;`), collapsing to 0px height before metadata loaded.
  3. `html5-qrcode` inserted opaque border shaders (`#qr-shaded-region`) on top of the collapsed 0px video, showing only the container background (`bg-slate-950`).
  4. `{ facingMode: 'environment' }` had no fallback for laptop webcams, failing on single-camera development environments.
- **Responsible Agents:** Camera & Browser Compatibility Agent, Frontend Development Agent
- **Resolution:**
  - Transitioned `QrScannerView.tsx` to a direct, permanently mounted `<video>` element managed via React `useRef`.
  - Configured attributes `autoPlay`, `muted`, and `playsInline` (`webkit-playsinline`) to satisfy mobile playback rules.
  - Implemented 3-tier camera fallback: `{ facingMode: { ideal: mode } }` → `{ facingMode: mode }` → `{ video: true }`.
  - Integrated native `BarcodeDetector` (hardware-accelerated) with an offscreen canvas fallback.
  - Added non-blocking transparent HUD reticle with animated laser beam.
  - Added Camera Flip (front/rear toggle) and Stop controls.
  - Wrapped viewport in a custom React `ErrorBoundary`.

## Bug SP-BUG-02: Backend Connection Refused (ECONNREFUSED 127.0.0.1:8000)
- **Severity:** High (Prevents login and API operations)
- **Reported Behavior:** Front-end displayed "Authentication failed. Check your credentials and backend connectivity."
- **Root Cause Analysis:** The Uvicorn process was terminated/unbound on port 8000 during sandbox background task reloads.
- **Responsible Agents:** Backend Development Agent, Master Orchestrator
- **Resolution:** Started FastAPI backend outside the sandbox bound to `0.0.0.0:8000`. Verified `/health` returned `HEALTHY` and validated authentication endpoint returns 200 OK.
