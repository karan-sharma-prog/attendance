import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Camera,
  CheckCircle2,
  AlertCircle,
  Loader2,
  ShieldCheck,
  RefreshCw,
  XCircle,
  Accessibility,
  MapPin,
} from 'lucide-react';
import { api, VerificationInitResponse } from '../../services/api';

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
  const [challenges, setChallenges] = useState<string[]>(transaction.active_challenges);
  const [geofenceVerified, setGeofenceVerified] = useState<boolean>(!transaction.geofence_required);
  const [geofenceInfo, setGeofenceInfo] = useState<string | null>(
    transaction.geofence_required ? null : 'Optional for this session'
  );
  const [checkingGeo, setCheckingGeo] = useState(false);

  const [cameraReady, setCameraReady] = useState(false);
  const [videoLive, setVideoLive] = useState(false);
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
    liveness_score: number | null;
    cosine_similarity: number | null;
  } | null>(null);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const stopCamera = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setCameraReady(false);
    setVideoLive(false);
  }, []);

  useEffect(() => {
    return () => stopCamera();
  }, [stopCamera]);

  const verifyGpsLocation = useCallback(async () => {
    setError(null);
    if (!navigator.geolocation) {
      if (transaction.geofence_required) {
        setError('Geolocation is unavailable in this browser but required by your instructor.');
        return false;
      }
      return true;
    }

    setCheckingGeo(true);
    setCurrentStage('GEOFENCE');
    try {
      const pos = await new Promise<GeolocationPosition>((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: true,
          timeout: 10000,
          maximumAge: 0,
        });
      });

      const res = await api.post('/verification/geofence', {
        transaction_id: transaction.transaction_id,
        latitude: pos.coords.latitude,
        longitude: pos.coords.longitude,
        accuracy_meters: pos.coords.accuracy,
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

  useEffect(() => {
    if (transaction.geofence_required) {
      void verifyGpsLocation();
    }
  }, [transaction.geofence_required, verifyGpsLocation]);

  const startFrontCamera = async () => {
    setCameraError(null);
    setError(null);
    if (transaction.geofence_required && !geofenceVerified) {
      const ok = await verifyGpsLocation();
      if (!ok) return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setCameraError('Browser camera API unavailable. Open via HTTPS or localhost.');
      return;
    }
    try {
      stopCamera();
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: 'user' }, width: { ideal: 640 }, height: { ideal: 480 } },
          audio: false,
        });
      } catch {
        // Fallback if specific facingMode/resolution constraint fails on device
        stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      }

      streamRef.current = stream;
      setCameraReady(true);

      // Attach stream directly to already-mounted <video> element to preserve mobile user gesture
      const video = videoRef.current;
      if (video) {
        video.srcObject = stream;
        video.setAttribute('playsinline', 'true');
        video.muted = true;
        await video.play();
        if (video.readyState >= 2 && video.videoWidth > 0) {
          setVideoLive(true);
        }
      }
      setCompletedStages((prev) => new Set([...prev, 'CAMERA_INIT']));
      setCurrentStage('CAMERA_INIT');
    } catch (err: any) {
      stopCamera();
      setCameraError(err?.message || 'Unable to access front camera. Check permissions and retry.');
    }
  };

  const captureFrameB64 = (): string => {
    const v = videoRef.current;
    const c = canvasRef.current;
    if (!v || !c || v.readyState < 2 || v.videoWidth === 0 || v.videoHeight === 0) {
      return '';
    }
    c.width = v.videoWidth;
    c.height = v.videoHeight;
    const ctx = c.getContext('2d');
    if (!ctx) return '';
    ctx.drawImage(v, 0, 0, c.width, c.height);
    return c.toDataURL('image/jpeg', 0.9);
  };

  const switchAccessibleChallenge = async () => {
    setError(null);
    try {
      const res = await api.post('/verification/challenge', {
        transaction_id: transaction.transaction_id,
        accessible_mode: true,
      });
      setChallenges(res.data.active_challenges);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not switch challenge.');
    }
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
          liveness_score: null,
          cosine_similarity: null,
        });
        return;
      }

      if (!cameraReady || !videoLive) {
        setError('Front camera stream is still initializing or blocked. Tap Retry Front Camera if preview is black.');
        setRunning(false);
        return;
      }

      // Capture 8 frames at 280ms intervals (~2.0s) so blinks & head movements are captured cleanly
      setCurrentStage('LIVENESS_RUNNING');
      const frames: string[] = [];
      for (let i = 0; i < 8; i++) {
        setCaptureProgress(`Capturing frame ${i + 1}/8 — perform: ${challenges.map((c) => c.replaceAll('_', ' ')).join(' & ')}`);
        const f = captureFrameB64();
        if (f) frames.push(f);
        if (i < 7) await new Promise((r) => setTimeout(r, 280));
      }
      setCaptureProgress('Analyzing liveness & anti-spoofing...');

      if (frames.length < 3) {
        setError('Camera returned empty frames. Please retry camera initialization.');
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

      setCaptureProgress('Matching 1:1 ArcFace biometric embedding...');
      setCurrentStage('IDENTITY_RUNNING');
      const frontalFrame = captureFrameB64() || frames[frames.length - 1];
      await api.post('/verification/identity', {
        transaction_id: transaction.transaction_id,
        image_base64: frontalFrame,
      });
      setCompletedStages((prev) => new Set([...prev, 'IDENTITY_RUNNING']));

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
    <div className="glass-panel p-6 sm:p-8 rounded-3xl space-y-6">
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
            onClick={() => {
              stopCamera();
              onCancel();
            }}
            className="px-3 py-1.5 rounded-xl glass-panel-subtle text-xs text-slate-300 hover:bg-white/10 flex items-center space-x-1"
          >
            <XCircle className="w-3.5 h-3.5" />
            <span>Cancel</span>
          </button>
        )}
      </div>

      {/* GPS Geofence Status Banner */}
      <div className="p-3 rounded-xl glass-panel-subtle flex flex-wrap items-center justify-between gap-2 text-xs">
        <div className="flex items-center space-x-2">
          <MapPin className={`w-4 h-4 ${geofenceVerified ? 'text-emerald-400' : 'text-amber-400'}`} />
          <span className="text-slate-200">
            GPS Geofence ({transaction.geofence_required ? `Required ≤ ${transaction.geofence_radius_meters}m` : 'Optional'}):
          </span>
          <span className="text-cyan-300">{checkingGeo ? 'Checking coordinates...' : geofenceInfo || 'Pending check'}</span>
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

      {error && (
        <div className="p-3.5 rounded-xl bg-red-950/60 border border-red-500/40 text-xs text-red-200 flex items-start space-x-2">
          <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {receipt ? (
        <div className="p-6 rounded-2xl bg-emerald-950/30 border border-emerald-500/40 space-y-4">
          <div className="flex items-center space-x-3">
            <CheckCircle2 className="w-8 h-8 text-emerald-400 shrink-0" />
            <div>
              <h3 className="text-base font-bold text-white">Attendance Successfully Recorded!</h3>
              <p className="text-xs text-emerald-300">
                Verified atomically in Neon PostgreSQL • Record ID: <span className="font-mono">{receipt.record_id}</span>
              </p>
            </div>
          </div>
          {receipt.liveness_score !== null && (
            <div className="text-xs text-slate-300">
              Anti-Spoofing Score: <span className="font-mono text-cyan-300">{receipt.liveness_score}</span> • ArcFace
              Cosine Similarity: <span className="font-mono text-cyan-300">{receipt.cosine_similarity}</span>
            </div>
          )}
          <button type="button" onClick={onCompleted} className="btn-primary px-5 py-2.5 rounded-xl text-xs font-semibold text-white">
            Done
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
          <div className="p-5 rounded-2xl glass-panel-subtle flex flex-col items-center space-y-4">
            {transaction.next_stage === 'NON_BIOMETRIC_REVIEW' ? (
              <div className="p-6 text-center space-y-2 text-xs text-cyan-200">
                <ShieldCheck className="w-10 h-10 text-cyan-400 mx-auto" />
                <div className="font-semibold">Authority-Approved Non-Biometric Accommodation Active</div>
                <p className="text-slate-400">Click Complete Verification below to record attendance.</p>
              </div>
            ) : (
              <>
                <div className="relative w-full max-w-sm aspect-[4/3] rounded-2xl overflow-hidden bg-slate-950 border border-white/10 flex items-center justify-center">
                  {/* Keep <video> always mounted so mobile Safari/Chrome attaches srcObject inside the user gesture */}
                  <video
                    ref={videoRef}
                    autoPlay
                    playsInline
                    muted
                    onLoadedMetadata={() => {
                      const v = videoRef.current;
                      if (v) void v.play();
                    }}
                    onPlaying={() => setVideoLive(true)}
                    className={`w-full h-full object-cover scale-x-[-1] ${cameraReady ? 'block' : 'hidden'}`}
                  />
                  {cameraReady && (
                    <div className="absolute inset-0 pointer-events-none flex items-center justify-center">
                      <div
                        className={`w-44 h-56 rounded-full border-2 ${
                          running ? 'border-cyan-400 animate-pulse' : 'border-dashed border-indigo-400/80'
                        }`}
                      />
                    </div>
                  )}
                  {!cameraReady && (
                    <div className="text-center p-6 space-y-2">
                      <Camera className="w-10 h-10 text-slate-500 mx-auto" />
                      <p className="text-xs text-slate-400">Front camera awaiting activation</p>
                    </div>
                  )}
                </div>
                <canvas ref={canvasRef} className="hidden" />

                {cameraError && (
                  <div className="w-full p-3 rounded-xl bg-amber-950/50 border border-amber-500/40 text-xs text-amber-200">
                    {cameraError}
                  </div>
                )}

                <div className="w-full max-w-sm p-3.5 rounded-xl bg-indigo-950/40 border border-indigo-500/30 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] font-bold text-cyan-300 uppercase">Liveness Challenges</span>
                    <button
                      type="button"
                      onClick={switchAccessibleChallenge}
                      className="text-[10px] text-slate-300 hover:text-white flex items-center space-x-1"
                    >
                      <Accessibility className="w-3 h-3" />
                      <span>Accessible Mode</span>
                    </button>
                  </div>
                  <div className="text-xs font-semibold text-white">
                    {captureProgress || `Perform during capture: ${challenges.map((c) => c.replaceAll('_', ' ')).join(' → ')}`}
                  </div>
                </div>

                <div className="flex flex-wrap gap-2 w-full max-w-sm">
                  {!cameraReady ? (
                    <button
                      type="button"
                      onClick={startFrontCamera}
                      className="flex-1 btn-primary py-2.5 px-4 rounded-xl text-xs font-semibold text-white flex items-center justify-center space-x-2"
                    >
                      <Camera className="w-4 h-4" />
                      <span>{cameraError ? 'Retry Front Camera' : 'Continue to Face Verification'}</span>
                    </button>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={runVerificationPipeline}
                        disabled={running || !videoLive}
                        className="flex-1 btn-cyan py-2.5 px-4 rounded-xl text-xs font-semibold text-white flex items-center justify-center space-x-2 disabled:opacity-60"
                      >
                        {running || !videoLive ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                        <span>
                          {!videoLive
                            ? 'Starting Camera...'
                            : running
                            ? 'Verifying Liveness & Identity...'
                            : 'Start Verification'}
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={startFrontCamera}
                        disabled={running}
                        className="px-3 py-2.5 rounded-xl glass-panel-subtle text-xs text-slate-300"
                        title="Re-initialize camera if preview looks stuck"
                      >
                        <RefreshCw className="w-3.5 h-3.5" />
                      </button>
                    </>
                  )}
                </div>
              </>
            )}

            {transaction.next_stage === 'NON_BIOMETRIC_REVIEW' && (
              <button
                type="button"
                onClick={runVerificationPipeline}
                disabled={running}
                className="btn-cyan py-2.5 px-5 rounded-xl text-xs font-semibold text-white"
              >
                {running ? 'Recording...' : 'Complete Verification'}
              </button>
            )}
          </div>

          <div className="p-5 rounded-2xl glass-panel-subtle space-y-3">
            <h3 className="text-xs font-bold text-slate-200 uppercase tracking-wider">Verification Pipeline Stages</h3>
            <div className="space-y-2.5">
              {STAGE_LIST.map((st) => {
                const done = completedStages.has(st.id);
                const active = currentStage === st.id && !done;
                return (
                  <div
                    key={st.id}
                    className={`p-3 rounded-xl text-xs flex items-center justify-between border ${
                      done
                        ? 'bg-emerald-950/40 border-emerald-500/40 text-emerald-200'
                        : active
                        ? 'bg-indigo-950/50 border-indigo-500 text-white'
                        : 'bg-white/[0.02] border-white/5 text-slate-500'
                    }`}
                  >
                    <span>{st.label}</span>
                    {done ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    ) : active ? (
                      <Loader2 className="w-4 h-4 animate-spin text-cyan-400" />
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
