import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Camera,
  CheckCircle2,
  AlertCircle,
  UserCheck,
  ShieldCheck,
  Trash2,
  RefreshCw,
  Loader2,
  Send,
} from 'lucide-react';
import { api } from '../../services/api';

type OrientationKey = 'front' | 'left' | 'right' | 'up' | 'down';

const ORIENTATIONS: { key: OrientationKey; label: string; instruction: string }[] = [
  { key: 'front', label: 'Front Face', instruction: 'Look directly into the camera with neutral expression.' },
  { key: 'left', label: 'Slight Left', instruction: 'Turn your head slightly (~15°) to your left.' },
  { key: 'right', label: 'Slight Right', instruction: 'Turn your head slightly (~15°) to your right.' },
  { key: 'up', label: 'Slight Upward', instruction: 'Tilt your chin slightly upward while keeping eyes visible.' },
  { key: 'down', label: 'Slight Downward', instruction: 'Tilt your head slightly downward toward the camera.' },
];

interface QualityMetrics {
  passed: boolean;
  brightness: number;
  sharpness: number;
  width: number;
  height: number;
  detector_mode: string;
  reasons: string[];
}

interface BiometricStatusData {
  student_id: string;
  biometric_status: string;
  biometric_consent_given: boolean;
  biometric_consent_at: string | null;
  non_biometric_exempt: boolean;
  accommodation_reason: string | null;
  latest_request_id: string | null;
  latest_request_status: string | null;
  latest_rejection_reason: string | null;
  embedding_ready: boolean;
  ml_readiness: {
    all_models_ready: boolean;
    models: Record<string, { loaded: boolean; filename: string; source: string }>;
  };
}

export function BiometricEnrollmentView() {
  const [statusData, setStatusData] = useState<BiometricStatusData | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [consentChecked, setConsentChecked] = useState(false);
  const [cameraActive, setCameraActive] = useState(false);
  const [videoLive, setVideoLive] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [activeStepIdx, setActiveStepIdx] = useState(0);
  const [captures, setCaptures] = useState<Partial<Record<OrientationKey, { image: string; quality: QualityMetrics }>>>({});
  const [validatingFrame, setValidatingFrame] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [isUpdateMode, setIsUpdateMode] = useState(false);

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
    setCameraActive(false);
    setVideoLive(false);
  }, []);

  const fetchStatus = useCallback(async () => {
    setLoadingStatus(true);
    try {
      const res = await api.get<BiometricStatusData>('/biometrics/status');
      setStatusData(res.data);
      setConsentChecked(res.data.biometric_consent_given);
    } catch (err: any) {
      setFeedback({ type: 'error', text: err?.response?.data?.detail || 'Failed to load biometric status.' });
    } finally {
      setLoadingStatus(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    return () => stopCamera();
  }, [fetchStatus, stopCamera]);

  const startFrontCamera = async () => {
    setCameraError(null);
    setFeedback(null);
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setCameraError('Camera API unavailable. Ensure HTTPS (or localhost) and modern browser support.');
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
        stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      }
      streamRef.current = stream;
      setCameraActive(true);
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
    } catch (err: any) {
      stopCamera();
      setCameraError(err?.message || 'Camera permission denied or front camera unavailable.');
    }
  };

  const captureAndValidateCurrentAngle = async () => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || video.readyState < 2 || video.videoWidth === 0) {
      setFeedback({ type: 'error', text: 'Camera frame is not ready yet. Wait a second or retry camera.' });
      return;
    }
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const dataUrl = canvas.toDataURL('image/jpeg', 0.9);
    const currentOrient = ORIENTATIONS[activeStepIdx].key;

    setValidatingFrame(true);
    setFeedback(null);
    try {
      const res = await api.post<QualityMetrics>('/biometrics/validate-frame', {
        orientation: currentOrient,
        image_base64: dataUrl,
      });
      if (!res.data.passed) {
        setFeedback({
          type: 'error',
          text: `${ORIENTATIONS[activeStepIdx].label} check failed: ${res.data.reasons.join(' ')}`,
        });
        return;
      }
      setCaptures((prev) => ({
        ...prev,
        [currentOrient]: { image: dataUrl, quality: res.data },
      }));
      if (activeStepIdx < ORIENTATIONS.length - 1) {
        setActiveStepIdx((i) => i + 1);
      } else {
        stopCamera();
        setFeedback({
          type: 'success',
          text: 'All 5 orientations passed quality validation! Review and submit for Authority approval.',
        });
      }
    } catch (err: any) {
      setFeedback({ type: 'error', text: err?.response?.data?.detail || 'Frame quality validation failed.' });
    } finally {
      setValidatingFrame(false);
    }
  };

  const handleSubmitEnrollment = async () => {
    if (!consentChecked) {
      setFeedback({ type: 'error', text: 'You must accept the Biometric Consent & Retention Policy first.' });
      return;
    }
    const samples = ORIENTATIONS.map((o) => ({
      orientation: o.key,
      image_base64: captures[o.key]?.image || '',
    }));
    if (samples.some((s) => !s.image_base64)) {
      setFeedback({ type: 'error', text: 'Please capture all 5 facial orientations first.' });
      return;
    }

    setSubmitting(true);
    setFeedback(null);
    try {
      const endpoint = isUpdateMode ? '/biometrics/update-request' : '/biometrics/register';
      const res = await api.post(endpoint, { consent_accepted: true, samples });
      stopCamera();
      setIsUpdateMode(false);
      setCaptures({});
      setActiveStepIdx(0);
      setFeedback({ type: 'success', text: res.data.message });
      await fetchStatus();
    } catch (err: any) {
      setFeedback({ type: 'error', text: err?.response?.data?.detail || 'Failed to submit enrollment.' });
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteBiometricData = async () => {
    if (!window.confirm('Withdraw consent and permanently delete your biometric profile?')) return;
    setSubmitting(true);
    try {
      await api.delete('/biometrics/profile');
      setCaptures({});
      setActiveStepIdx(0);
      setIsUpdateMode(false);
      setFeedback({ type: 'success', text: 'Biometric profile deleted and consent withdrawn.' });
      await fetchStatus();
    } catch (err: any) {
      setFeedback({ type: 'error', text: err?.response?.data?.detail || 'Could not delete profile.' });
    } finally {
      setSubmitting(false);
    }
  };

  if (loadingStatus) {
    return (
      <div className="glass-panel p-10 rounded-2xl flex justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-indigo-400" />
      </div>
    );
  }

  const bioStatus = statusData?.biometric_status || 'NOT_REGISTERED';
  const canEnrollNow =
    bioStatus === 'NOT_REGISTERED' || bioStatus === 'REJECTED' || (bioStatus === 'APPROVED' && isUpdateMode);

  return (
    <div className="space-y-6">
      {feedback && (
        <div
          className={`p-4 rounded-xl text-xs flex items-start space-x-2 border ${
            feedback.type === 'success'
              ? 'bg-emerald-950/50 border-emerald-500/40 text-emerald-200'
              : 'bg-red-950/60 border-red-500/40 text-red-200'
          }`}
        >
          {feedback.type === 'success' ? (
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
          ) : (
            <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
          )}
          <span>{feedback.text}</span>
        </div>
      )}

      {/* Status Header */}
      <div className="glass-panel p-6 rounded-2xl flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center space-x-3">
          <div className="w-11 h-11 rounded-2xl bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center">
            <UserCheck className="w-5 h-5 text-indigo-400" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h2 className="text-base font-bold text-white">Biometric Enrollment Status</h2>
              <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-indigo-500/20 text-cyan-300 border border-indigo-500/30">
                {bioStatus.replaceAll('_', ' ')}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              {statusData?.non_biometric_exempt
                ? `Non-biometric accommodation active: ${statusData.accommodation_reason}`
                : statusData?.latest_rejection_reason && bioStatus === 'REJECTED'
                ? `Rejection reason: ${statusData.latest_rejection_reason}`
                : 'AES-256-GCM encrypted enrollment • Raw video is never stored.'}
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-2">
          {bioStatus === 'APPROVED' && !isUpdateMode && (
            <button
              type="button"
              onClick={() => setIsUpdateMode(true)}
              className="px-3.5 py-2 rounded-xl btn-primary text-xs font-semibold text-white"
            >
              Request Profile Update
            </button>
          )}
          {bioStatus !== 'NOT_REGISTERED' && (
            <button
              type="button"
              onClick={handleDeleteBiometricData}
              disabled={submitting}
              className="px-3.5 py-2 rounded-xl bg-red-950/60 hover:bg-red-900/70 border border-red-500/30 text-xs text-red-300 flex items-center space-x-1.5"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span>Withdraw &amp; Delete Data</span>
            </button>
          )}
        </div>
      </div>

      {/* ML Weights Readiness Transparency */}
      {statusData && !statusData.ml_readiness.all_models_ready && (
        <div className="p-4 rounded-xl bg-amber-950/40 border border-amber-500/30 text-xs text-amber-200 space-y-1">
          <div className="font-semibold">Phase 5 Active • Phase 6 ML Weights Pending Approval</div>
          <p className="text-[11px] text-amber-200/80">
            OpenCV frame quality validation (lighting, sharpness, resolution) is active now. Pretrained ML weights
            (BlazeFace, MediaPipe FaceLandmarker, MiniFASNet, ArcFace ResNet-100) will be verified and activated in Phase 6.
          </p>
        </div>
      )}

      {/* 5-Orientation Enrollment Capture Workflow */}
      {canEnrollNow && (
        <div className="glass-panel p-6 rounded-2xl space-y-6">
          {/* Consent Checkbox */}
          <label className="p-4 rounded-xl glass-panel-subtle flex items-start space-x-3 cursor-pointer">
            <input
              type="checkbox"
              checked={consentChecked}
              onChange={(e) => setConsentChecked(e.target.checked)}
              className="mt-1 accent-indigo-500"
            />
            <span className="text-xs text-slate-300 leading-relaxed">
              <strong className="text-white">Biometric Consent &amp; Data Retention Policy:</strong> I consent to
              SmartPresence capturing 5 facial orientations for identity verification. Facial embeddings are stored
              encrypted with AES-256-GCM, are never shared externally, and may be deleted at any time. Students unable
              to use facial biometrics may request an institutional non-biometric alternative from the Administrator.
            </span>
          </label>

          {/* Orientation Progress Pills */}
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
            {ORIENTATIONS.map((o, idx) => {
              const done = Boolean(captures[o.key]);
              const isCurrent = idx === activeStepIdx;
              return (
                <button
                  key={o.key}
                  type="button"
                  onClick={() => setActiveStepIdx(idx)}
                  className={`p-3 rounded-xl text-left transition border ${
                    done
                      ? 'bg-emerald-950/40 border-emerald-500/40 text-emerald-200'
                      : isCurrent
                      ? 'bg-indigo-950/50 border-indigo-500 text-white'
                      : 'glass-panel-subtle border-white/10 text-slate-400'
                  }`}
                >
                  <div className="text-[11px] font-bold flex items-center justify-between">
                    <span>{o.label}</span>
                    {done && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />}
                  </div>
                  <div className="text-[10px] mt-1 opacity-80">
                    {done ? `Sharp: ${captures[o.key]!.quality.sharpness}` : `Step ${idx + 1}/5`}
                  </div>
                </button>
              );
            })}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
            {/* Live Front Camera */}
            <div className="p-5 rounded-2xl glass-panel-subtle flex flex-col items-center space-y-4">
              <div className="relative w-full max-w-sm aspect-[4/3] rounded-2xl overflow-hidden bg-slate-950 border border-white/10 flex items-center justify-center">
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
                  className={`w-full h-full object-cover scale-x-[-1] ${cameraActive ? 'block' : 'hidden'}`}
                />
                {cameraActive ? (
                  <div className="absolute inset-0 pointer-events-none flex items-center justify-center">
                    <div className="w-44 h-56 rounded-full border-2 border-dashed border-cyan-400/70" />
                  </div>
                ) : (
                  <div className="text-center p-6 space-y-2">
                    <Camera className="w-10 h-10 text-slate-500 mx-auto" />
                    <p className="text-xs text-slate-400">Front camera preview inactive</p>
                  </div>
                )}
              </div>
              <canvas ref={canvasRef} className="hidden" />

              {cameraError && (
                <div className="w-full p-3 rounded-xl bg-amber-950/50 border border-amber-500/40 text-xs text-amber-200">
                  {cameraError}
                </div>
              )}

              <div className="text-xs text-cyan-300 text-center font-medium">
                Current Pose: <strong>{ORIENTATIONS[activeStepIdx].label}</strong> —{' '}
                {ORIENTATIONS[activeStepIdx].instruction}
              </div>

              <div className="flex flex-wrap gap-2 w-full max-w-sm">
                {!cameraActive ? (
                  <button
                    type="button"
                    onClick={startFrontCamera}
                    className="flex-1 btn-primary py-2.5 px-4 rounded-xl text-xs font-semibold text-white flex items-center justify-center space-x-2"
                  >
                    <Camera className="w-4 h-4" />
                    <span>{cameraError ? 'Retry Front Camera' : 'Enable Front Camera'}</span>
                  </button>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={captureAndValidateCurrentAngle}
                      disabled={validatingFrame || !videoLive}
                      className="flex-1 btn-cyan py-2.5 px-4 rounded-xl text-xs font-semibold text-white flex items-center justify-center space-x-2 disabled:opacity-60"
                    >
                      {validatingFrame || !videoLive ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
                      <span>{!videoLive ? 'Starting Camera...' : `Capture ${ORIENTATIONS[activeStepIdx].label}`}</span>
                    </button>
                    <button
                      type="button"
                      onClick={stopCamera}
                      className="px-3 py-2.5 rounded-xl glass-panel-subtle text-xs text-slate-300"
                    >
                      Stop
                    </button>
                  </>
                )}
              </div>
            </div>

            {/* Captured Thumbnails & Submission */}
            <div className="p-5 rounded-2xl glass-panel-subtle space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-white">Captured Orientation Samples</h3>
                <button
                  type="button"
                  onClick={() => {
                    setCaptures({});
                    setActiveStepIdx(0);
                  }}
                  className="text-xs text-slate-400 hover:text-white flex items-center space-x-1"
                >
                  <RefreshCw className="w-3 h-3" />
                  <span>Reset</span>
                </button>
              </div>

              <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
                {ORIENTATIONS.map((o) => {
                  const cap = captures[o.key];
                  return (
                    <div key={o.key} className="space-y-1 text-center">
                      <div className="aspect-square rounded-xl overflow-hidden bg-slate-900 border border-white/10 flex items-center justify-center">
                        {cap ? (
                          <img src={cap.image} alt={o.label} className="w-full h-full object-cover" />
                        ) : (
                          <span className="text-[10px] text-slate-600">{o.key}</span>
                        )}
                      </div>
                      <div className="text-[10px] text-slate-400">{o.label}</div>
                    </div>
                  );
                })}
              </div>

              <button
                type="button"
                onClick={handleSubmitEnrollment}
                disabled={submitting || Object.keys(captures).length < 5 || !consentChecked}
                className="w-full btn-primary py-3 rounded-xl text-xs font-semibold text-white flex items-center justify-center space-x-2 disabled:opacity-50"
              >
                {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                <span>Submit 5-Angle Biometric Enrollment for Authority Approval</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
