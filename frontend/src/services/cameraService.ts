/**
 * Centralized Camera & MediaStream Coordinator for SmartPresence.
 * Guarantees that:
 * 1. Only ONE active MediaStream holds the hardware camera at any time (QR rear camera is always
 *    released before front facial verification camera initializes).
 * 2. Three-tier constraint fallback supports mobile rear/front cameras AND laptop webcams.
 * 3. Video elements are configured with muted, playsInline, webkit-playsinline, and autoplay
 *    before assigning srcObject to satisfy iOS WKWebView and Android WebView policies.
 */

export type CameraFacing = 'environment' | 'user';

let activeGlobalStream: MediaStream | null = null;
let activeOwner: string | null = null;

export function stopGlobalCameraStream(expectedOwner?: string): void {
  if (expectedOwner && activeOwner && activeOwner !== expectedOwner) {
    return;
  }
  if (activeGlobalStream) {
    activeGlobalStream.getTracks().forEach((track) => {
      try {
        track.stop();
      } catch {
        // Ignore already-stopped track
      }
    });
    activeGlobalStream = null;
    activeOwner = null;
  }
}

export interface AcquireCameraOptions {
  owner: 'qr-scanner' | 'facial-verification' | 'biometric-enrollment';
  facingMode: CameraFacing;
  idealWidth?: number;
  idealHeight?: number;
}

export async function acquireCameraStream(options: AcquireCameraOptions): Promise<MediaStream> {
  if (typeof window !== 'undefined' && !window.isSecureContext) {
    throw new Error(
      'Camera requires a secure context (HTTPS or localhost). Open SmartPresence over HTTPS.'
    );
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    throw new Error(
      'Camera API unavailable in this browser/WebView. Ensure camera permissions are enabled.'
    );
  }

  // Always release any previously held camera stream (e.g. QR scanner -> facial verification)
  stopGlobalCameraStream();
  // Brief yield so mobile hardware sensors finish releasing the lock
  await new Promise((r) => setTimeout(r, 120));

  const { facingMode, idealWidth = 1280, idealHeight = 720, owner } = options;
  let stream: MediaStream | null = null;

  try {
    console.info(`[CameraService:${owner}] Tier 1: requesting ideal facingMode=${facingMode}`);
    stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: facingMode },
        width: { ideal: idealWidth },
        height: { ideal: idealHeight },
      },
      audio: false,
    });
  } catch (tier1Err) {
    console.warn(`[CameraService:${owner}] Tier 1 failed, trying simple facingMode`, tier1Err);
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode },
        audio: false,
      });
    } catch (tier2Err) {
      console.warn(`[CameraService:${owner}] Tier 2 failed, falling back to any camera`, tier2Err);
      stream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: false,
      });
    }
  }

  if (!stream) {
    throw new Error('Camera hardware did not return a MediaStream.');
  }

  const tracks = stream.getVideoTracks();
  if (!tracks.length || tracks[0].readyState !== 'live') {
    stream.getTracks().forEach((t) => t.stop());
    throw new Error('Camera returned no active live video track.');
  }

  activeGlobalStream = stream;
  activeOwner = owner;
  console.info(
    `[CameraService:${owner}] Stream acquired: track="${tracks[0].label || 'default'}", state=${tracks[0].readyState}`
  );
  return stream;
}

export interface VideoAttachCallbacks {
  onLive: (resolution: string) => void;
  onError: (message: string) => void;
}

export function attachStreamToVideo(
  video: HTMLVideoElement,
  stream: MediaStream,
  callbacks: VideoAttachCallbacks
): void {
  video.muted = true;
  video.playsInline = true;
  video.setAttribute('playsinline', 'true');
  video.setAttribute('webkit-playsinline', 'true');
  video.autoplay = true;
  video.srcObject = stream;

  const tryPlay = () => {
    video.play().catch((err) => {
      console.error('[CameraService] video.play() rejected:', err);
      if (err?.name !== 'AbortError') {
        callbacks.onError(err?.message || 'Unable to start live video playback.');
      }
    });
  };

  const emitLive = () => {
    const res =
      video.videoWidth > 0 && video.videoHeight > 0
        ? `${video.videoWidth}x${video.videoHeight}`
        : '';
    callbacks.onLive(res);
  };

  video.onloadedmetadata = () => {
    console.info(
      `[CameraService] loadedmetadata: ${video.videoWidth}x${video.videoHeight}, readyState=${video.readyState}`
    );
    tryPlay();
  };

  video.oncanplay = () => {
    emitLive();
  };

  video.onplaying = () => {
    emitLive();
  };

  if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
    tryPlay();
  }
}

export function formatCameraError(err: any): string {
  const name = String(err?.name || '').toLowerCase();
  const msg = String(err?.message || err || '');
  const lower = msg.toLowerCase();

  if (name.includes('notallowed') || lower.includes('permission') || lower.includes('denied')) {
    return 'Camera permission denied. Enable camera access in app/browser settings and tap Retry.';
  }
  if (name.includes('notfound') || lower.includes('notfound') || lower.includes('no camera')) {
    return 'No camera hardware detected on this device.';
  }
  if (name.includes('notreadable') || lower.includes('in use') || lower.includes('could not start')) {
    return 'Camera is currently occupied by another application. Close other camera apps and retry.';
  }
  return msg || 'Unable to initialize camera. Please check permissions and retry.';
}
