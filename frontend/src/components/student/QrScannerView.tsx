import { useState, useEffect, useRef, useCallback } from 'react';
import jsQR from 'jsqr';
import {
  Camera,
  QrCode,
  AlertCircle,
  ShieldCheck,
  Loader2,
  FlipHorizontal,
  CheckCircle2,
  X,
  Flashlight,
} from 'lucide-react';
import { api, VerificationInitResponse } from '../../services/api';
import {
  acquireCameraStream,
  attachStreamToVideo,
  stopGlobalCameraStream,
  formatCameraError,
} from '../../services/cameraService';
import { FacialVerificationFlow } from './FacialVerificationFlow';
import { ErrorBoundary } from '../common/ErrorBoundary';

interface QrScannerViewProps {
  initialToken?: string | null;
  onTokenConsumed?: () => void;
  onGoToEnrollment?: () => void;
}

function extractTokenFromInput(raw: string): string {
  const trimmed = raw.trim();
  if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) {
    try {
      const parsed = new URL(trimmed);
      const tok = parsed.searchParams.get('token');
      if (tok) return tok.trim();
    } catch {
      // fall through
    }
  }
  return trimmed;
}

export function QrScannerView({ initialToken = null, onTokenConsumed, onGoToEnrollment }: QrScannerViewProps) {
  const [scanning, setScanning] = useState(false);
  const [videoLive, setVideoLive] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [facingMode, setFacingMode] = useState<'environment' | 'user'>('environment');
  const [torchSupported, setTorchSupported] = useState(false);
  const [torchOn, setTorchOn] = useState(false);
  const [streamResolution, setStreamResolution] = useState<string | null>(null);

  const [manualToken, setManualToken] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [txResult, setTxResult] = useState<VerificationInitResponse | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [detectedBadge, setDetectedBadge] = useState<string | null>(null);

  // References
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const scanIntervalRef = useRef<number | null>(null);
  const isDecodingRef = useRef(false);
  const hasDecodedRef = useRef(false);
  const startingRef = useRef(false);
  const consumedInitialRef = useRef<string | null>(null);

  /**
   * Stop camera stream cleanly: releases hardware tracks so LED turns off immediately.
   */
  const stopCameraCleanly = useCallback(async () => {
    startingRef.current = false;
    isDecodingRef.current = false;

    if (scanIntervalRef.current) {
      clearInterval(scanIntervalRef.current);
      scanIntervalRef.current = null;
    }

    stopGlobalCameraStream('qr-scanner');
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => {
        try {
          track.stop();
        } catch {
          // ignore
        }
      });
      streamRef.current = null;
    }

    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }

    setScanning(false);
    setVideoLive(false);
    setTorchOn(false);
    setTorchSupported(false);
    setStreamResolution(null);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      void stopCameraCleanly();
    };
  }, [stopCameraCleanly]);

  /**
   * Validate and submit token to backend verification endpoint.
   */
  const submitScannedQrToken = useCallback(
    async (rawInput: string) => {
      const tokenText = extractTokenFromInput(rawInput);
      if (!tokenText) return;

      setVerifyError(null);
      setSubmitting(true);
      try {
        const res = await api.post<VerificationInitResponse>('/verification/qr', {
          qr_token: tokenText,
        });
        await stopCameraCleanly();
        setTxResult(res.data);
      } catch (err: any) {
        setVerifyError(err?.response?.data?.detail || 'QR verification failed.');
      } finally {
        setSubmitting(false);
      }
    },
    [stopCameraCleanly]
  );

  // Auto-consume token if loaded via default camera direct URL
  useEffect(() => {
    if (initialToken && consumedInitialRef.current !== initialToken) {
      consumedInitialRef.current = initialToken;
      void submitScannedQrToken(initialToken).finally(() => {
        if (onTokenConsumed) onTokenConsumed();
      });
    }
  }, [initialToken, onTokenConsumed, submitScannedQrToken]);

  /**
   * Start live camera stream with bulletproof constraints & fallbacks.
   */
  const startCamera = async (targetFacing: 'environment' | 'user' = facingMode) => {
    if (startingRef.current) return;
    startingRef.current = true;
    hasDecodedRef.current = false;
    setCameraError(null);
    setVerifyError(null);
    setDetectedBadge(null);
    setScanning(true);
    setVideoLive(false);

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setCameraError('Camera API unavailable. Ensure you are using HTTPS (or localhost) and modern browser support.');
      startingRef.current = false;
      setScanning(false);
      return;
    }

    try {
      await stopCameraCleanly();
      startingRef.current = true;
      setScanning(true);

      const stream = await acquireCameraStream({
        owner: 'qr-scanner',
        facingMode: targetFacing,
        idealWidth: 1280,
        idealHeight: 720,
      });

      streamRef.current = stream;

      // Detect flashlight/torch capability on mobile rear camera
      const track = stream.getVideoTracks()[0];
      try {
        const caps = track?.getCapabilities?.() as any;
        setTorchSupported(Boolean(caps && 'torch' in caps));
      } catch {
        setTorchSupported(false);
      }

      const video = videoRef.current;
      if (!video) {
        throw new Error('Video viewport component was not mounted.');
      }

      attachStreamToVideo(video, stream, {
        onLive: (res) => {
          setVideoLive(true);
          if (res) setStreamResolution(res);
        },
        onError: (msg) => {
          setCameraError(msg);
        },
      });

      // Start continuous QR frame decoding loop
      startDecodingLoop();
    } catch (err: any) {
      console.error('[QrScanner] Camera startup failed:', err);
      startingRef.current = false;
      setScanning(false);
      setVideoLive(false);
      setCameraError(formatCameraError(err));
    } finally {
      startingRef.current = false;
    }
  };

  const toggleTorch = async () => {
    const track = streamRef.current?.getVideoTracks()[0];
    if (!track) return;
    try {
      const next = !torchOn;
      await track.applyConstraints({ advanced: [{ torch: next } as any] });
      setTorchOn(next);
    } catch {
      setTorchSupported(false);
    }
  };

  /**
   * Continuous QR frame analyzer using native BarcodeDetector + synchronous jsQR pixel decoding.
   * Works reliably on Android Chrome, iOS Safari, Windows/Mac Chrome, Edge, and Firefox.
   */
  const startDecodingLoop = () => {
    if (scanIntervalRef.current) {
      clearInterval(scanIntervalRef.current);
    }

    const hasBarcodeDetector = typeof window !== 'undefined' && 'BarcodeDetector' in window;
    let barcodeDetector: any = null;
    if (hasBarcodeDetector) {
      try {
        barcodeDetector = new (window as any).BarcodeDetector({ formats: ['qr_code'] });
      } catch {
        barcodeDetector = null;
      }
    }

    scanIntervalRef.current = window.setInterval(async () => {
      if (isDecodingRef.current || hasDecodedRef.current) return;
      const video = videoRef.current;
      if (!video || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || video.videoWidth === 0) {
        return;
      }

      isDecodingRef.current = true;

      try {
        // Path 1: Native hardware-accelerated BarcodeDetector (when available)
        if (barcodeDetector) {
          try {
            const barcodes = await barcodeDetector.detect(video);
            if (barcodes && barcodes.length > 0 && barcodes[0].rawValue) {
              void handleDecodedQr(barcodes[0].rawValue);
              return;
            }
          } catch {
            // Fall through to jsQR
          }
        }

        // Path 2: Synchronous jsQR decoding on canvas ImageData (works on 100% of mobile & desktop browsers)
        const canvas = canvasRef.current;
        if (canvas) {
          const vw = video.videoWidth;
          const vh = video.videoHeight;
          // Preserve crisp detail up to 960px wide so dense signed JWT/URL QR codes decode cleanly
          const scale = vw > 960 ? 960 / vw : 1;
          const cw = Math.max(1, Math.round(vw * scale));
          const ch = Math.max(1, Math.round(vh * scale));
          if (canvas.width !== cw || canvas.height !== ch) {
            canvas.width = cw;
            canvas.height = ch;
          }
          const ctx = canvas.getContext('2d', { willReadFrequently: true });
          if (ctx) {
            ctx.drawImage(video, 0, 0, cw, ch);
            const imageData = ctx.getImageData(0, 0, cw, ch);
            const code = jsQR(imageData.data, cw, ch, { inversionAttempts: 'attemptBoth' });
            if (code && code.data) {
              void handleDecodedQr(code.data);
              return;
            }
          }
        }
      } catch (decodeErr) {
        console.debug('[QrScanner] Frame decode error:', decodeErr);
      } finally {
        isDecodingRef.current = false;
      }
    }, 110);
  };

  /**
   * Called when a QR code has been successfully decoded from the video stream.
   */
  const handleDecodedQr = async (decodedText: string) => {
    if (hasDecodedRef.current) return;
    hasDecodedRef.current = true;
    console.info('[QrScanner] Successfully detected QR code:', decodedText);

    // Optional audio feedback
    try {
      const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.frequency.setValueAtTime(880, audioCtx.currentTime); // A5
      gain.gain.setValueAtTime(0.1, audioCtx.currentTime);
      osc.start();
      osc.stop(audioCtx.currentTime + 0.12);
    } catch {
      // AudioContext may be restricted before interaction
    }

    setDetectedBadge('QR Code Detected! Authenticating...');
    await stopCameraCleanly();
    await submitScannedQrToken(decodedText);
  };

  /**
   * Switch between front and rear cameras cleanly.
   */
  const toggleCameraFacing = async () => {
    const nextMode = facingMode === 'environment' ? 'user' : 'environment';
    setFacingMode(nextMode);
    if (scanning) {
      await startCamera(nextMode);
    }
  };

  return (
    <ErrorBoundary fallbackTitle="QR Scanner View Encountered an Issue" onReset={() => void stopCameraCleanly()}>
      {/* Hidden offscreen canvas and container for fallback frame decoding */}
      <canvas ref={canvasRef} className="hidden" />
      <div id="sp-qr-hidden-shim" className="hidden" />

      <div className="glass-panel p-6 sm:p-8 rounded-3xl space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 pb-4">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center space-x-2">
              <QrCode className="w-5 h-5 text-cyan-400" />
              <span>Classroom QR Authentication</span>
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              Scan instructor&apos;s dynamic QR token using your device camera or paste the attendance token directly.
            </p>
          </div>

          {scanning && (
            <div className="flex items-center space-x-2">
              <span className="inline-flex items-center px-2.5 py-1 rounded-full text-[11px] font-medium bg-emerald-950/70 text-emerald-400 border border-emerald-500/30">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 mr-1.5 animate-pulse" />
                Camera Active {streamResolution ? `(${streamResolution})` : ''}
              </span>
            </div>
          )}
        </div>

        {submitting && !txResult && (
          <div className="p-4 rounded-xl bg-indigo-950/50 border border-indigo-500/40 text-xs text-indigo-200 flex items-center space-x-2">
            <Loader2 className="w-4 h-4 animate-spin text-cyan-400" />
            <span>Validating QR cryptographic signature, active timetable session, and student enrollment...</span>
          </div>
        )}

        {detectedBadge && (
          <div className="p-3.5 rounded-xl bg-emerald-950/60 border border-emerald-500/40 text-xs text-emerald-200 flex items-center space-x-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{detectedBadge}</span>
          </div>
        )}

        {verifyError && (
          <div className="p-3.5 rounded-xl bg-red-950/60 border border-red-500/40 text-xs text-red-200 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-start space-x-2">
              <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
              <span>{verifyError}</span>
            </div>
            {onGoToEnrollment && verifyError.toLowerCase().includes('biometric') && (
              <button
                type="button"
                onClick={onGoToEnrollment}
                className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-[11px] font-semibold text-white"
              >
                Go to Biometric Enrollment
              </button>
            )}
          </div>
        )}

        {txResult ? (
          <FacialVerificationFlow
            transaction={txResult}
            onCancel={() => setTxResult(null)}
            onCompleted={() => setTxResult(null)}
          />
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
            {/* Live Camera Scanner Viewport */}
            <div className="p-5 rounded-2xl glass-panel-subtle flex flex-col items-center space-y-4">
              <div className="relative w-full max-w-[420px] aspect-[4/3] rounded-2xl overflow-hidden bg-slate-950 border border-white/10 shadow-2xl flex items-center justify-center">
                {/* 
                  Video element is permanently mounted in the React DOM.
                  Attributes muted, autoPlay, and playsInline guarantee compatibility on mobile browsers.
                */}
                <video
                  ref={videoRef}
                  autoPlay
                  muted
                  playsInline
                  className={`w-full h-full object-cover transition-opacity duration-300 ${
                    videoLive ? 'opacity-100' : 'opacity-0'
                  }`}
                />

                {/* Inactive Placeholder */}
                {!scanning && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center p-6 space-y-3 bg-slate-950/90 text-center">
                    <div className="w-14 h-14 rounded-2xl bg-indigo-950/70 border border-indigo-500/30 flex items-center justify-center">
                      <Camera className="w-7 h-7 text-indigo-400" />
                    </div>
                    <div>
                      <p className="text-xs font-semibold text-white">Scanner Camera Standby</p>
                      <p className="text-[11px] text-slate-400 mt-0.5">
                        Click below to activate rear camera (or laptop webcam)
                      </p>
                    </div>
                  </div>
                )}

                {/* Starting / Loading State */}
                {scanning && !videoLive && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center p-6 space-y-3 bg-slate-950 text-center">
                    <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
                    <p className="text-xs text-slate-300 font-medium">Connecting to camera sensor...</p>
                    <p className="text-[10px] text-slate-500">Grant browser permission if prompted</p>
                  </div>
                )}

                {/* Transparent QR Target Reticle & Scanning Animation */}
                {scanning && videoLive && (
                  <div className="absolute inset-0 pointer-events-none flex flex-col items-center justify-center p-4">
                    {/* Viewfinder Target Box */}
                    <div className="relative w-52 h-52 sm:w-60 sm:h-60 rounded-2xl border-2 border-cyan-400/70 shadow-[0_0_25px_rgba(34,211,238,0.25)] flex items-center justify-center overflow-hidden">
                      {/* Corner Target Markers */}
                      <div className="absolute top-0 left-0 w-4 h-4 border-t-4 border-l-4 border-cyan-300 -mt-0.5 -ml-0.5 rounded-tl-sm" />
                      <div className="absolute top-0 right-0 w-4 h-4 border-t-4 border-r-4 border-cyan-300 -mt-0.5 -mr-0.5 rounded-tr-sm" />
                      <div className="absolute bottom-0 left-0 w-4 h-4 border-b-4 border-l-4 border-cyan-300 -mb-0.5 -ml-0.5 rounded-bl-sm" />
                      <div className="absolute bottom-0 right-0 w-4 h-4 border-b-4 border-r-4 border-cyan-300 -mb-0.5 -mr-0.5 rounded-br-sm" />

                      {/* Animated Laser Beam */}
                      <div className="absolute inset-x-0 h-0.5 bg-gradient-to-r from-transparent via-cyan-300 to-transparent shadow-[0_0_8px_#22d3ee] animate-pulse" />
                    </div>

                    <div className="mt-4 px-3 py-1 rounded-full bg-black/60 backdrop-blur-md border border-white/10 text-[11px] text-slate-200">
                      Align QR code inside box
                    </div>
                  </div>
                )}
              </div>

              {cameraError && (
                <div className="w-full max-w-[420px] p-3 rounded-xl bg-amber-950/60 border border-amber-500/40 text-xs text-amber-200 flex items-start space-x-2">
                  <AlertCircle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                  <span>{cameraError}</span>
                </div>
              )}

              {/* Camera Action Controls */}
              <div className="flex flex-wrap gap-2.5 w-full max-w-[420px]">
                {!scanning ? (
                  <button
                    type="button"
                    onClick={() => void startCamera(facingMode)}
                    disabled={submitting}
                    className="flex-1 btn-primary py-2.5 px-4 rounded-xl text-xs font-semibold text-white flex items-center justify-center space-x-2 shadow-lg"
                  >
                    <Camera className="w-4 h-4" />
                    <span>{cameraError ? 'Retry Camera' : 'Open Rear Camera Scanner'}</span>
                  </button>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => void stopCameraCleanly()}
                      className="flex-1 py-2.5 px-4 rounded-xl bg-red-600/80 hover:bg-red-600 text-xs font-semibold text-white flex items-center justify-center space-x-2 transition"
                    >
                      <X className="w-4 h-4" />
                      <span>Stop Camera</span>
                    </button>

                    <button
                      type="button"
                      onClick={toggleCameraFacing}
                      title="Switch between front and rear cameras"
                      className="py-2.5 px-3.5 rounded-xl glass-panel hover:bg-white/10 text-xs font-medium text-slate-200 flex items-center justify-center space-x-1.5 transition border border-white/10"
                    >
                      <FlipHorizontal className="w-4 h-4 text-cyan-400" />
                      <span className="hidden sm:inline">
                        {facingMode === 'environment' ? 'Front' : 'Rear'}
                      </span>
                    </button>

                    {torchSupported && (
                      <button
                        type="button"
                        onClick={() => void toggleTorch()}
                        title="Toggle flashlight"
                        className={`py-2.5 px-3.5 rounded-xl text-xs font-medium flex items-center justify-center space-x-1.5 transition border ${
                          torchOn
                            ? 'bg-amber-500/20 border-amber-400/50 text-amber-300'
                            : 'glass-panel border-white/10 text-slate-200 hover:bg-white/10'
                        }`}
                      >
                        <Flashlight className="w-4 h-4" />
                      </button>
                    )}
                  </>
                )}
              </div>
            </div>

            {/* Direct Signed URL / Token Submission */}
            <div className="p-5 rounded-2xl glass-panel-subtle space-y-4">
              <h3 className="text-sm font-semibold text-white">Verify Attendance URL or Token</h3>
              <p className="text-xs text-slate-400">
                Paste the verification URL or signed token generated by your instructor to validate without a camera.
              </p>
              <textarea
                rows={4}
                value={manualToken}
                onChange={(e) => setManualToken(e.target.value)}
                placeholder="https://.../attend/verify?token=v1...."
                className="w-full glass-input p-3 rounded-xl text-xs font-mono"
              />
              <button
                type="button"
                disabled={!manualToken.trim() || submitting}
                onClick={() => submitScannedQrToken(manualToken)}
                className="btn-cyan py-2.5 px-5 rounded-xl text-xs font-semibold text-white flex items-center space-x-2 disabled:opacity-50"
              >
                {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
                <span>Validate QR Token with Backend</span>
              </button>
            </div>
          </div>
        )}
      </div>
    </ErrorBoundary>
  );
}
