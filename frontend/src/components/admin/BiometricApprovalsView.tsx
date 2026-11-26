import { useState, useEffect, useCallback } from 'react';
import { ShieldCheck, CheckCircle2, XCircle, Loader2, UserCheck, AlertTriangle } from 'lucide-react';
import { api, getAccessToken } from '../../services/api';

interface AdminBiometricRequest {
  request_id: string;
  student_id: string;
  student_name: string;
  roll_number: string;
  email: string;
  department: string;
  semester: number;
  request_type: string;
  status: string;
  student_biometric_status: string;
  embedding_ready: boolean;
  orientation_metrics: Record<string, { brightness: number; sharpness: number; width: number; height: number }> | null;
  rejection_reason: string | null;
  created_at: string;
}

export function BiometricApprovalsView() {
  const [requests, setRequests] = useState<AdminBiometricRequest[]>([]);
  const [previewUrls, setPreviewUrls] = useState<Record<string, string>>({});
  const [rejectReasons, setRejectReasons] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [processingId, setProcessingId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadRequests = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<AdminBiometricRequest[]>('/admin/biometrics/requests');
      setRequests(res.data);

      // Load protected preview images using authenticated fetch -> memory ObjectURL (never localStorage)
      const token = getAccessToken();
      const urls: Record<string, string> = {};
      await Promise.all(
        res.data.slice(0, 12).map(async (item) => {
          try {
            const imgRes = await fetch(`/api/v1/admin/biometrics/requests/${item.request_id}/preview`, {
              headers: { Authorization: `Bearer ${token}` },
            });
            if (imgRes.ok) {
              const blob = await imgRes.blob();
              urls[item.request_id] = URL.createObjectURL(blob);
            }
          } catch {
            // No preview image available
          }
        })
      );
      setPreviewUrls(urls);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to load biometric requests.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRequests();
  }, [loadRequests]);

  const handleApprove = async (requestId: string, nonBiometric = false) => {
    setProcessingId(requestId);
    setError(null);
    setFeedback(null);
    try {
      await api.post('/admin/biometrics/approve', {
        request_id: requestId,
        grant_non_biometric_alternative: nonBiometric,
        accommodation_reason: nonBiometric ? 'Approved non-biometric institutional exemption' : undefined,
      });
      setFeedback(nonBiometric ? 'Approved with non-biometric accommodation.' : 'Biometric enrollment approved.');
      await loadRequests();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Approval failed.');
    } finally {
      setProcessingId(null);
    }
  };

  const handleReject = async (requestId: string) => {
    const reason = (rejectReasons[requestId] || '').trim();
    if (reason.length < 5) {
      setError('Enter a clear rejection reason (at least 5 characters).');
      return;
    }
    setProcessingId(requestId);
    setError(null);
    setFeedback(null);
    try {
      await api.post('/admin/biometrics/reject', { request_id: requestId, rejection_reason: reason });
      setFeedback('Biometric request rejected and student notified.');
      await loadRequests();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Rejection failed.');
    } finally {
      setProcessingId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="glass-panel p-6 rounded-2xl flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center space-x-2">
            <ShieldCheck className="w-5 h-5 text-cyan-400" />
            <span>Authority Biometric Verification Console</span>
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Verify student identity against institutional records before approving biometric attendance eligibility.
          </p>
        </div>
        <button onClick={loadRequests} className="px-3.5 py-2 rounded-xl glass-panel-subtle text-xs text-cyan-300">
          Refresh Queue
        </button>
      </div>

      {feedback && (
        <div className="p-3.5 rounded-xl bg-emerald-950/50 border border-emerald-500/40 text-xs text-emerald-200">
          {feedback}
        </div>
      )}
      {error && (
        <div className="p-3.5 rounded-xl bg-red-950/60 border border-red-500/40 text-xs text-red-200 flex items-center space-x-2">
          <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {loading ? (
        <div className="glass-panel p-10 rounded-2xl flex justify-center">
          <Loader2 className="w-6 h-6 animate-spin text-indigo-400" />
        </div>
      ) : requests.length === 0 ? (
        <div className="glass-panel p-10 rounded-2xl text-center space-y-2">
          <UserCheck className="w-10 h-10 text-slate-500 mx-auto" />
          <div className="text-sm font-semibold text-slate-200">No Biometric Requests Submitted</div>
          <p className="text-xs text-slate-400">
            Student facial registration and profile update requests will appear here for authority review.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {requests.map((item) => (
            <div key={item.request_id} className="glass-panel p-6 rounded-2xl grid grid-cols-1 md:grid-cols-4 gap-6 items-center">
              <div className="flex justify-center">
                {previewUrls[item.request_id] ? (
                  <img
                    src={previewUrls[item.request_id]}
                    alt={item.student_name}
                    className="w-36 h-36 rounded-2xl object-cover border border-white/10"
                  />
                ) : (
                  <div className="w-36 h-36 rounded-2xl bg-slate-900 border border-white/10 flex items-center justify-center text-xs text-slate-500">
                    No Preview
                  </div>
                )}
              </div>

              <div className="md:col-span-2 space-y-2 text-xs">
                <div className="flex items-center space-x-2">
                  <span className="text-base font-bold text-white">{item.student_name}</span>
                  <span className="px-2 py-0.5 rounded bg-indigo-500/20 text-cyan-300 font-mono text-[10px]">
                    {item.request_type}
                  </span>
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                      item.status === 'APPROVED'
                        ? 'bg-emerald-500/20 text-emerald-300'
                        : item.status === 'REJECTED'
                        ? 'bg-red-500/20 text-red-300'
                        : 'bg-amber-500/20 text-amber-300'
                    }`}
                  >
                    {item.status}
                  </span>
                </div>
                <div className="text-slate-300">
                  Roll: <span className="font-mono">{item.roll_number}</span> • {item.email}
                </div>
                <div className="text-slate-400">
                  {item.department} • Semester {item.semester}
                </div>
                {item.orientation_metrics && (
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {Object.entries(item.orientation_metrics).map(([ang, m]) => (
                      <span key={ang} className="px-2 py-0.5 rounded bg-white/5 text-[10px] text-slate-300">
                        {ang}: sharp {m.sharpness} / light {m.brightness}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              <div className="space-y-2">
                {item.status === 'PENDING_APPROVAL' ? (
                  <>
                    <button
                      type="button"
                      disabled={processingId === item.request_id}
                      onClick={() => handleApprove(item.request_id, false)}
                      className="w-full py-2 px-3 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-xs font-semibold text-white flex items-center justify-center space-x-1.5"
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      <span>Approve Profile</span>
                    </button>
                    <button
                      type="button"
                      disabled={processingId === item.request_id}
                      onClick={() => handleApprove(item.request_id, true)}
                      className="w-full py-2 px-3 rounded-xl glass-panel-subtle hover:bg-white/10 text-xs text-cyan-300"
                    >
                      Grant Non-Biometric Alternative
                    </button>
                    <input
                      type="text"
                      placeholder="Rejection reason..."
                      value={rejectReasons[item.request_id] || ''}
                      onChange={(e) =>
                        setRejectReasons((prev) => ({ ...prev, [item.request_id]: e.target.value }))
                      }
                      className="w-full glass-input px-3 py-1.5 rounded-lg text-xs"
                    />
                    <button
                      type="button"
                      disabled={processingId === item.request_id}
                      onClick={() => handleReject(item.request_id)}
                      className="w-full py-2 px-3 rounded-xl bg-red-600/80 hover:bg-red-600 text-xs font-semibold text-white flex items-center justify-center space-x-1.5"
                    >
                      <XCircle className="w-3.5 h-3.5" />
                      <span>Reject</span>
                    </button>
                  </>
                ) : (
                  <div className="text-xs text-slate-400 text-center">
                    Reviewed ({item.status})
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
