import { useState, useEffect, useRef, useCallback } from 'react';
import {
  CheckCircle2,
  AlertCircle,
  ShieldCheck,
  XCircle,
  MapPin,
  FlipHorizontal,
} from 'lucide-react';
import { api, VerificationInitResponse } from '../../services/api';
import {
  acquireCameraStream,
  attachStreamToVideo,
  stopGlobalCameraStream,
  formatCameraError,
  CameraFacing,
} from '../../services/cameraService';
import { getCurrentGeoPosition } from '../../services/geolocationService';
import { ErrorBoundary } from '../common/ErrorBoundary';

interface FacialVerificationFlowProps {
  transaction: VerificationInitResponse;
  onCancel: () => void;
  onCompleted: () => void;
}

type StageId =
  | 'GEOFENCE'
  | 'CAMERA_INIT'
  | 'LIVENESS_RUNNING'
  | 'LIVENESS_VERIFIED'
  | 'IDENTITY_RUNNING'
  | 'RECORDING'
  | 'DONE';

const STAGE_LIST: { id: StageId; label: string }[] = [
  { id: 'GEOFENCE', label: '1. GPS classroom geofence check' },
  { id: 'CAMERA_INIT', label: '2. Front camera initialized' },
  { id: 'LIVENESS_RUNNING', label: '3. Face detection & liveness challenges' },
  { id: 'LIVENESS_VERIFIED', label: '4. MiniFASNet & landmark liveness verified' },
  { id: 'IDENTITY_RUNNING', label: '5. ArcFace 1:1 identity matching' },
  { id: 'RECORDING', label: '6. Server decision engine & atomic record' },
  { id: 'DONE', label: '7. Attendance successfully recorded' },
];

export function FacialVerificationFlow({ transaction, onCancel, onCompleted }: FacialVerificationFlowProps) {
  const [geofenceVerified, setGeofenceVerified] = useState<boolean>(!transaction.geofence_required);
  const [geofenceInfo, setGeofenceInfo] = useState<string | null>(
    transaction.geofence_required ? null : 'Optional for this session'
  );
  const [checkingGeo, setCheckingGeo] = useState(false);

  const [cameraReady, setCameraReady] = useState(false);
  const [videoLive, setVideoLive] = useState(false);
  const [facingMode, setFacingMode] = useState<CameraFacing>('user');
  const [streamResolution, setStreamResolution] = useState<string | null>(null);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [captureProgress, setCaptureProgress] = useState<string | null>(null);
  const [currentStage, setCurrentStage] = useState<StageId | null>(null);

  const [completedStages, setCompletedStages] = useState<Set<StageId>>(
    () => (transaction.geofence_required ? new Set() : new Set<StageId>(['GEOFENCE']))
  );
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<{
    record_id: string;
    marked_at: string;
    subject_code: string;
    subject_name: string;
    liveness_score: number | null;
    cosine_similarity: number | null;
  } | null>(null);
  const [autoPipelineTriggered, setAutoPipelineTriggered] = useState(false);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  // Guard against React StrictMode double-mount
  const cameraStartingRef = useRef(false);
  const autoCameraStartedRef = useRef(false);

  const stopCamera = useCallback(() => {
    cameraStartingRef.current = false;
    stopGlobalCameraStream('facial-verification');
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setCameraReady(false);
    setVideoLive(false);
    setStreamResolution(null);
  }, []);

  useEffect(() => {
    return () => stopCamera();
  }, [stopCamera]);

  const verifyGpsLocation = useCallback(async () => {
    setError(null);
    setCheckingGeo(true);
    setCurrentStage('GEOFENCE');
    try {
      const pos = await getCurrentGeoPosition();

      const res = await api.post('/verification/geofence', {
        transaction_id: transaction.transaction_id,
        latitude: pos.latitude,
        longitude: pos.longitude,
        accuracy_meters: pos.accuracy,
      });
      setGeofenceVerified(true);
      setGeofenceInfo(res.data.detail);
      setCompletedStages((prev) => new Set([...prev, 'GEOFENCE']));
      return true;
    } catch (err: any) {
      const msg =
        err?.response?.data?.detail ||
        err?.message ||
        'GPS permission denied. Enable location access to verify classroom proximity.';
      if (transaction.geofence_required) {
        setError(msg);
        return false;
      }
      setGeofenceInfo('GPS skipped (optional)');
      return true;
    } finally {
      setCheckingGeo(false);
    }
  }, [transaction.geofence_required, transaction.transaction_id]);

  // Auto-run GPS verification if required
  useEffect(() => {
    if (transaction.geofence_required) {
      void verifyGpsLocation();
    }
  }, [transaction.geofence_required, verifyGpsLocation]);

  /**
   * startFrontCamera — robust version for desktop + mobile browsers.
   *
   * Key fixes:
   *  1. Guard cameraStartingRef prevents duplicate calls (React StrictMode, button double-tap).
   *  2. We set srcObject and all video attributes BEFORE calling play().
   *  3. We call play() ONLY inside onloadedmetadata so the stream is guaranteed decoded.
   *  4. Fallback: if readyState >= HAVE_ENOUGH_DATA the metadata already fired; play immediately.
   *  5. We listen to oncanplay / onplaying as additional signals to set videoLive.
   */
  const startFrontCamera = async (targetFacing: CameraFacing = facingMode) => {
    if (cameraStartingRef.current) return;
    cameraStartingRef.current = true;

    setCameraError(null);
    setError(null);

    if (transaction.geofence_required && !geofenceVerified) {
      const ok = await verifyGpsLocation();
      if (!ok) {
        cameraStartingRef.current = false;
        return;
      }
    }

    try {
      stopCamera();
      cameraStartingRef.current = true;

      const stream = await acquireCameraStream({
        owner: 'facial-verification',
        facingMode: targetFacing,
        idealWidth: 640,
        idealHeight: 480,
      });

      streamRef.current = stream;
      setCameraReady(true);

      const video = videoRef.current;
      if (!video) {
        throw new Error('Video element not mounted yet. Please retry.');
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

      setCompletedStages((prev) => new Set([...prev, 'CAMERA_INIT']));
      setCurrentStage('CAMERA_INIT');
    } catch (err: any) {
      console.error('[Camera] startFrontCamera error:', err);
      stopCamera();
      setCameraError(formatCameraError(err));
    } finally {
      cameraStartingRef.current = false;
    }
  };

  // Auto-open front camera immediately once QR + credentials are verified (and GPS is satisfied)
  useEffect(() => {
    if (
      transaction.next_stage === 'NON_BIOMETRIC_REVIEW' ||
      receipt ||
      autoCameraStartedRef.current
    ) {
      return;
    }
    if (transaction.geofence_required && !geofenceVerified) {
      return;
    }
    autoCameraStartedRef.current = true;
    void startFrontCamera('user');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transaction.next_stage, transaction.geofence_required, geofenceVerified, receipt]);

  // Auto-run face detection, liveness & authority-approved biometric match once camera is live
  useEffect(() => {
    if (
      !cameraReady ||
      !videoLive ||
      running ||
      receipt ||
      autoPipelineTriggered ||
      transaction.next_stage === 'NON_BIOMETRIC_REVIEW'
    ) {
      return;
    }
    setCaptureProgress('Face camera live — blink now...');
    const timer = window.setTimeout(() => {
      setAutoPipelineTriggered(true);
      void runVerificationPipeline();
    }, 600);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraReady, videoLive, running, receipt, autoPipelineTriggered, transaction.next_stage]);

  const toggleFacingMode = () => {
    const next: CameraFacing = facingMode === 'user' ? 'environment' : 'user';
    setFacingMode(next);
    if (cameraReady) {
      void startFrontCamera(next);
    }
  };

  /**
   * captureFrameB64 — safely captures a JPEG frame from the live video element.
   * Returns empty string if the video is not ready (guards against black frames).
   */
  const captureFrameB64 = (): string => {
    const v = videoRef.current;
    const c = canvasRef.current;
    if (!v || !c) {
      console.warn('[Capture] Video or canvas ref is null');
      return '';
    }
    if (v.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
      console.warn('[Capture] Video not ready — readyState:', v.readyState);
      return '';
    }
    if (v.videoWidth === 0 || v.videoHeight === 0) {
      console.warn('[Capture] Video dimensions zero — stream may still be starting');
      return '';
    }
    if (v.paused || v.ended) {
      console.warn('[Capture] Video is paused or ended');
      return '';
    }
    // Scale down to max 480px width for ultra-fast mobile upload while keeping facial landmarks sharp
    const scale = v.videoWidth > 480 ? 480 / v.videoWidth : 1;
    c.width = Math.max(1, Math.round(v.videoWidth * scale));
    c.height = Math.max(1, Math.round(v.videoHeight * scale));
    const ctx = c.getContext('2d');
    if (!ctx) return '';
    ctx.drawImage(v, 0, 0, c.width, c.height);
    const dataUrl = c.toDataURL('image/jpeg', 0.78);
    if (dataUrl.length < 1000) {
      console.warn('[Capture] Data URL suspiciously short — may be blank frame');
    }
    return dataUrl;
  };

  const runVerificationPipeline = async () => {
    setError(null);
    setRunning(true);
    try {
      if (transaction.geofence_required && !geofenceVerified) {
        const geoOk = await verifyGpsLocation();
        if (!geoOk) {
          setRunning(false);
          return;
        }
      }

      if (transaction.next_stage === 'NON_BIOMETRIC_REVIEW') {
        setCurrentStage('RECORDING');
        const compRes = await api.post('/verification/complete', {
          transaction_id: transaction.transaction_id,
        });
        setCompletedStages((prev) => new Set([...prev, 'RECORDING', 'DONE']));
        setCurrentStage('DONE');
        setReceipt({
          record_id: compRes.data.attendance_record_id,
          marked_at: compRes.data.marked_at,
          subject_code: compRes.data.subject_code || transaction.subject_code,
          subject_name: compRes.data.subject_name || transaction.subject_name,
          liveness_score: null,
          cosine_similarity: null,
        });
        return;
      }

      if (!cameraReady || !videoLive) {
        setError('Camera is not ready. Please initialize the front camera first.');
        setRunning(false);
        return;
      }

      // Fast blink capture: 6 frames at 180 ms (~1.08s) + instant photo match & submit
      setCurrentStage('LIVENESS_RUNNING');
      const frames: string[] = [];
      for (let i = 0; i < 6; i++) {
        setCaptureProgress(`Blink now (${i + 1}/6)`);
        await new Promise((r) => setTimeout(r, 180));
        const f = captureFrameB64();
        if (f) frames.push(f);
      }
      setCaptureProgress('Verifying blink & matching photo...');

      if (frames.length < 3) {
        setError('Camera returned blank frames. Ensure good lighting and retry camera initialization.');
        setRunning(false);
        setCaptureProgress(null);
        return;
      }

      await api.post('/verification/liveness', {
        transaction_id: transaction.transaction_id,
        frames_base64: frames,
      });
      setCompletedStages((prev) => new Set([...prev, 'LIVENESS_RUNNING', 'LIVENESS_VERIFIED']));
      setCurrentStage('LIVENESS_VERIFIED');

      // Identity match (ArcFace 1:1)
      setCaptureProgress('Matching 1:1 ArcFace biometric embedding...');
      setCurrentStage('IDENTITY_RUNNING');
      const frontalFrame = captureFrameB64() || frames[frames.length - 1];
      await api.post('/verification/identity', {
        transaction_id: transaction.transaction_id,
        image_base64: frontalFrame,
      });
      setCompletedStages((prev) => new Set([...prev, 'IDENTITY_RUNNING']));

      // Record attendance
      setCaptureProgress('Recording attendance in Neon database...');
      setCurrentStage('RECORDING');
      const completeRes = await api.post('/verification/complete', {
        transaction_id: transaction.transaction_id,
      });
      stopCamera();
      setCompletedStages((prev) => new Set([...prev, 'RECORDING', 'DONE']));
      setCurrentStage('DONE');
      setCaptureProgress(null);
      setReceipt({
        record_id: completeRes.data.attendance_record_id,
        marked_at: completeRes.data.marked_at,
        subject_code: completeRes.data.subject_code || transaction.subject_code,
        subject_name: completeRes.data.subject_name || transaction.subject_name,
        liveness_score: completeRes.data.liveness_score,
        cosine_similarity: completeRes.data.cosine_similarity,
      });
    } catch (err: any) {
      setCaptureProgress(null);
      setError(err?.response?.data?.detail || 'Verification stage failed. Adjust lighting/pose and retry.');
    } finally {
      setRunning(false);
    }
  };

  return (
    <ErrorBoundary fallbackTitle="Facial Verification Camera Error" onReset={stopCamera}>
    <div className="glass-panel p-6 sm:p-8 rounded-3xl space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 pb-4">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center space-x-2">
            <ShieldCheck className="w-5 h-5 text-cyan-400" />
            <span>Biometric Liveness, Geofence &amp; Identity Verification</span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            {transaction.subject_code}: {transaction.subject_name}
          </p>
        </div>
        {!receipt && (
          <button
            type="button"
            onClick={() => { stopCamera(); onCancel(); }}
            className="px-3 py-1.5 rounded-xl glass-panel-subtle text-xs text-slate-300 hover:bg-white/10 flex items-center space-x-1"
          >
            <XCircle className="w-3.5 h-3.5" />
            <span>Cancel</span>
          </button>
        )}
      </div>

      {/* GPS Geofence */}
      <div className="p-3 rounded-xl glass-panel-subtle flex flex-wrap items-center justify-between gap-2 text-xs">
        <div className="flex items-center space-x-2">
          <MapPin className={`w-4 h-4 ${geofenceVerified ? 'text-emerald-400' : 'text-amber-400'}`} />
          <span className="text-slate-200">
            GPS Geofence (
            {transaction.geofence_required
              ? `Required ≤ ${transaction.geofence_radius_meters}m`
              : 'Optional'}
            ):
          </span>
          <span className="text-cyan-300">
            {checkingGeo ? 'Checking coordinates...' : geofenceInfo || 'Pending check'}
          </span>
        </div>
        {!geofenceVerified && (
          <button
            type="button"
            onClick={() => void verifyGpsLocation()}
            disabled={checkingGeo}
            className="px-3 py-1 rounded-lg bg-indigo-600/80 hover:bg-indigo-500 text-[11px] font-semibold text-white"
          >
            {checkingGeo ? 'Locating...' : 'Verify GPS Location'}
          </button>
        )}
      </div>

      {/* Stage tracker — also silences the unused currentStage variable warning */}
      <div className="flex flex-col space-y-1.5">
        {STAGE_LIST.map((s) => {
          const done = completedStages.has(s.id);
          const active = currentStage === s.id;
          return (
            <div key={s.id} className="flex items-center space-x-2">
              <div
                className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                  done ? 'bg-emerald-400' : active ? 'bg-cyan-400 animate-pulse' : 'bg-slate-600'
                }`}
              />
              <span className={`text-xs ${done ? 'text-emerald-300' : active ? 'text-cyan-200' : 'text-slate-400'}`}>
                {s.label}
              </span>
            </div>
          );
        })}
      </div>

      {error && (
        <div className="p-3.5 rounded-xl bg-red-950/60 border border-red-500/40 text-xs text-red-200 flex items-start space-x-2">
          <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {receipt ? (
        (() => {
          const dt = new Date(receipt.marked_at);
          const dayStr = dt.toLocaleDateString(undefined, { weekday: 'long' });
          const dateStr = dt.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' });
          const timeStr = dt.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
          return (
            <div className="p-6 rounded-2xl bg-emerald-950/35 border border-emerald-500/40 space-y-4">
              <div className="flex items-center space-x-3">
                <CheckCircle2 className="w-9 h-9 text-emerald-400 shrink-0" />
                <div>
                  <h3 className="text-base font-bold text-white">Attendance Submitted &amp; Sent to Teacher Portal</h3>
                  <p className="text-xs text-emerald-300">
                    Matched against authority-approved biometric profile • Recorded in Neon PostgreSQL
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs">
                <div className="p-3 rounded-xl bg-black/30 border border-white/10">
                  <div className="text-[10px] text-slate-400 uppercase">Class / Subject</div>
                  <div className="font-bold text-white mt-0.5">{receipt.subject_code}</div>
                  <div className="text-[11px] text-slate-300 truncate">{receipt.subject_name}</div>
                </div>
                <div className="p-3 rounded-xl bg-black/30 border border-white/10">
                  <div className="text-[10px] text-slate-400 uppercase">Day</div>
                  <div className="font-bold text-cyan-300 mt-0.5">{dayStr}</div>
                </div>
                <div className="p-3 rounded-xl bg-black/30 border border-white/10">
                  <div className="text-[10px] text-slate-400 uppercase">Date</div>
                  <div className="font-bold text-white mt-0.5">{dateStr}</div>
                </div>
                <div className="p-3 rounded-xl bg-black/30 border border-white/10">
                  <div className="text-[10px] text-slate-400 uppercase">Time</div>
                  <div className="font-bold text-emerald-300 mt-0.5 font-mono">{timeStr}</div>
                </div>
              </div>

              {receipt.liveness_score !== null && (
                <div className="text-xs text-slate-300">
                  Anti-Spoofing Liveness:{' '}
                  <span className="font-mono text-cyan-300">{receipt.liveness_score}</span> • Authority Biometric Match:{' '}
                  <span className="font-mono text-cyan-300">{receipt.cosine_similarity}</span> • Record:{' '}
                  <span className="font-mono text-slate-400">{receipt.record_id.slice(0, 8)}</span>
                </div>
              )}

              <button
                type="button"
                onClick={onCompleted}
                className="btn-primary px-5 py-2.5 rounded-xl text-xs font-semibold text-white"
              >
                Done
              </button>
            </div>
          );
        })()
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
          {/* Camera panel */}
          <div className="p-5 rounded-2xl glass-panel-subtle flex flex-col items-center space-y-4">
            {transaction.next_stage === 'NON_BIOMETRIC_REVIEW' ? (
              <div className="p-6 text-center space-y-2 text-xs text-cyan-200">
                <ShieldCheck className="w-10 h-10 text-cyan-400 mx-auto" />
                <div className="font-semibold">Authority-Approved Non-Biometric Accommodation Active</div>
                <p className="text-slate-400">Click Complete Verification below to record attendance.</p>
              </div>
            ) : (
              <>
                {/*
                  VIDEO ELEMENT: Always kept mounted in the DOM so the ref is
                  valid when startFrontCamera calls video.srcObject = stream.
                  Hidden via CSS when camera is inactive — NOT via conditional
                  rendering — to prevent the ref becoming null.
                */}
                <div
                  className="relative w-full max-w-sm rounded-2xl overflow-hidden bg-slate-950 border border-white/10"
                  style={{ aspectRatio: '4/3' }}
                >
                  <video
                    ref={videoRef}
                    autoPlay
                    playsInline
                    muted
                    className={`w-full h-full object-cover transition-opacity duration-300 ${
                      cameraReady && videoLive ? 'opacity-100' : 'opacity-0'
                    }`}
                    style={{
                      transform: facingMode === 'user' ? 'scaleX(-1)' : 'none',
                    }}
                  />
                  <canvas ref={canvasRef} style={{ display: 'none' }} />
                  {!cameraReady && (
                    <div className="absolute inset-0 flex flex-col items-center justify-center space-y-2 bg-slate-950/90">
                      <span className="text-3xl">📷</span>
                      <p className="text-xs text-slate-400">Camera preview inactive</p>
                    </div>
                  )}
                  {cameraReady && !videoLive && (
                    <div className="absolute inset-0 flex flex-col items-center justify-center space-y-2 bg-slate-950/90">
                      <p className="text-xs text-cyan-300 animate-pulse">Initializing front camera stream...</p>
                    </div>
                  )}
                  {cameraReady && videoLive && (
                    <div className="absolute inset-0 pointer-events-none flex flex-col items-center justify-center">
                      <div className="w-40 h-52 rounded-full border-2 border-dashed border-cyan-400/70" />
                      {streamResolution && (
                        <span className="mt-2 px-2 py-0.5 rounded-full bg-black/60 text-[10px] text-emerald-300">
                          Live {streamResolution}
                        </span>
                      )}
                    </div>
                  )}
                </div>

                {/* Camera controls */}
                <div className="flex flex-wrap gap-2 w-full max-w-sm justify-center">
                  {!cameraReady ? (
                    <button
                      type="button"
                      onClick={() => void startFrontCamera(facingMode)}
                      disabled={running}
                      className="flex-1 btn-primary py-2.5 px-4 rounded-xl text-xs font-semibold text-white"
                    >
                      {cameraError ? 'Retry Front Camera' : 'Open Front Camera'}
                    </button>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={stopCamera}
                        className="flex-1 px-4 py-2.5 rounded-xl bg-red-600/80 hover:bg-red-600 text-xs font-semibold text-white"
                      >
                        Stop Camera
                      </button>
                      <button
                        type="button"
                        onClick={toggleFacingMode}
                        className="px-3.5 py-2.5 rounded-xl glass-panel hover:bg-white/10 text-xs text-slate-200 flex items-center space-x-1.5 border border-white/10"
                      >
                        <FlipHorizontal className="w-4 h-4 text-cyan-400" />
                        <span>Switch</span>
                      </button>
                    </>
                  )}
                </div>

                {cameraError && (
                  <div className="w-full p-3 rounded-xl bg-amber-950/50 border border-amber-500/40 text-xs text-amber-200 flex items-start space-x-2">
                    <AlertCircle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                    <span>{cameraError}</span>
                  </div>
                )}

                {captureProgress && (
                  <div className="w-full text-xs text-cyan-300 text-center">{captureProgress}</div>
                )}
              </>
            )}
          </div>

          {/* Verification controls */}
          <div className="flex flex-col space-y-4 p-5 rounded-2xl glass-panel-subtle">
            <div className="text-xs text-slate-300 space-y-1.5">
              <div>Liveness Check: <span className="text-cyan-300 font-semibold">Blink your eyes naturally (any number of times)</span></div>
              <div>Camera: <span className={cameraReady && videoLive ? 'text-emerald-400' : 'text-amber-400'}>{cameraReady && videoLive ? 'Live — Auto-Verifying' : 'Starting front camera...'}</span></div>
              <p className="text-[11px] text-slate-400 pt-1">
                Look at the camera and blink naturally. Your live face is matched securely on the server against your authority-approved biometric profile.
              </p>
            </div>

            <button
              type="button"
              onClick={() => {
                setAutoPipelineTriggered(true);
                void runVerificationPipeline();
              }}
              disabled={running || (!cameraReady && transaction.next_stage !== 'NON_BIOMETRIC_REVIEW')}
              className="w-full py-3 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white text-xs font-bold"
            >
              {running ? 'Checking Blink & Matching Photo...' : error ? 'Retry Blink Check & Submit' : 'Blink & Submit Now'}
            </button>
          </div>
        </div>
      )}
    </div>
    </ErrorBoundary>
  );
}
