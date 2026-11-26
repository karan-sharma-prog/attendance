import { useState, useEffect, useRef, useCallback } from 'react';
import { Html5Qrcode } from 'html5-qrcode';
import {
  Camera,
  QrCode,
  AlertCircle,
  RefreshCw,
  ShieldCheck,
  Loader2,
} from 'lucide-react';
import { api, VerificationInitResponse } from '../../services/api';
import { FacialVerificationFlow } from './FacialVerificationFlow';

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
      // Fallback to raw text
    }
  }
  return trimmed;
}

export function QrScannerView({ initialToken = null, onTokenConsumed, onGoToEnrollment }: QrScannerViewProps) {
  const [scanning, setScanning] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [manualToken, setManualToken] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [txResult, setTxResult] = useState<VerificationInitResponse | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const scannerRef = useRef<Html5Qrcode | null>(null);
  const consumedInitialRef = useRef<string | null>(null);
  const regionId = 'sp-qr-reader-region';

  const stopCameraCleanly = useCallback(async () => {
    if (scannerRef.current) {
      try {
        if (scannerRef.current.isScanning) {
          await scannerRef.current.stop();
        }
        scannerRef.current.clear();
      } catch {
        // Ignore cleanup errors if stream already closed
      }
      scannerRef.current = null;
    }
    // Ensure any underlying MediaStream video tracks in the scanner container are released on mobile
    const region = document.getElementById(regionId);
    if (region) {
      region.querySelectorAll('video').forEach((v) => {
        const ms = v.srcObject as MediaStream | null;
        if (ms) {
          ms.getTracks().forEach((t) => t.stop());
          v.srcObject = null;
        }
      });
    }
    setScanning(false);
  }, []);

  useEffect(() => {
    return () => {
      void stopCameraCleanly();
    };
  }, [stopCameraCleanly]);

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

  // Immediately validate QR token when opened via default mobile camera URL (/attend/verify?token=...)
  useEffect(() => {
    if (initialToken && consumedInitialRef.current !== initialToken) {
      consumedInitialRef.current = initialToken;
      void submitScannedQrToken(initialToken).finally(() => {
        if (onTokenConsumed) onTokenConsumed();
      });
    }
  }, [initialToken, onTokenConsumed, submitScannedQrToken]);

  const startRearCameraScanner = async () => {
    setCameraError(null);
    setVerifyError(null);
    setTxResult(null);

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setCameraError(
        'Browser camera API unavailable. Ensure you are using HTTPS (or localhost) and grant camera permissions.'
      );
      return;
    }

    try {
      await stopCameraCleanly();
      const html5Qr = new Html5Qrcode(regionId);
      scannerRef.current = html5Qr;
      setScanning(true);

      await html5Qr.start(
        { facingMode: 'environment' },
        { fps: 10, qrbox: { width: 240, height: 240 } },
        async (decodedText) => {
          await stopCameraCleanly();
          await submitScannedQrToken(decodedText);
        },
        () => {
          // Ignore per-frame decode misses while scanning
        }
      );
    } catch (err: any) {
      setScanning(false);
      const msg = String(err?.message || err || '');
      if (msg.toLowerCase().includes('permission') || msg.toLowerCase().includes('notallowed')) {
        setCameraError('Camera permission denied. Please allow camera access in your browser settings and retry.');
      } else {
        setCameraError(`Unable to access rear camera: ${msg || 'No camera detected'}`);
      }
    }
  };

  return (
    <div className="glass-panel p-6 sm:p-8 rounded-3xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 pb-4">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center space-x-2">
            <QrCode className="w-5 h-5 text-cyan-400" />
            <span>Classroom QR Authentication</span>
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Scan with your phone&apos;s default camera or the built-in rear camera scanner below.
          </p>
        </div>
      </div>

      {submitting && !txResult && (
        <div className="p-4 rounded-xl bg-indigo-950/50 border border-indigo-500/40 text-xs text-indigo-200 flex items-center space-x-2">
          <Loader2 className="w-4 h-4 animate-spin text-cyan-400" />
          <span>Validating QR signature, active attendance window, and enrollment...</span>
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
          {/* Rear Camera Preview Region */}
          <div className="p-5 rounded-2xl glass-panel-subtle flex flex-col items-center space-y-4">
            <div
              id={regionId}
              className="w-full max-w-sm min-h-[260px] rounded-2xl overflow-hidden bg-slate-950/80 border border-white/10 flex items-center justify-center"
            >
              {!scanning && (
                <div className="text-center p-6 space-y-2">
                  <Camera className="w-10 h-10 text-slate-500 mx-auto" />
                  <p className="text-xs text-slate-400">Rear camera inactive</p>
                </div>
              )}
            </div>

            {cameraError && (
              <div className="w-full p-3 rounded-xl bg-amber-950/50 border border-amber-500/40 text-xs text-amber-200">
                {cameraError}
              </div>
            )}

            <div className="flex gap-3 w-full max-w-sm">
              {!scanning ? (
                <button
                  type="button"
                  onClick={startRearCameraScanner}
                  disabled={submitting}
                  className="flex-1 btn-primary py-2.5 px-4 rounded-xl text-xs font-semibold text-white flex items-center justify-center space-x-2"
                >
                  <Camera className="w-4 h-4" />
                  <span>{cameraError ? 'Retry Rear Camera' : 'Open Rear Camera Scanner'}</span>
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => void stopCameraCleanly()}
                  className="flex-1 py-2.5 px-4 rounded-xl bg-red-600/80 hover:bg-red-600 text-xs font-semibold text-white flex items-center justify-center space-x-2"
                >
                  <RefreshCw className="w-4 h-4" />
                  <span>Stop Camera</span>
                </button>
              )}
            </div>
          </div>

          {/* Direct Signed URL / Token Submission */}
          <div className="p-5 rounded-2xl glass-panel-subtle space-y-4">
            <h3 className="text-sm font-semibold text-white">Verify Attendance URL or Token</h3>
            <p className="text-xs text-slate-400">
              Paste the verification URL or signed token generated by your instructor to validate without a webcam.
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
  );
}
