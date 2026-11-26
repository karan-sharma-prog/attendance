import { useState, useEffect, useCallback, FormEvent } from 'react';
import { Calendar, CheckCircle2, XCircle, Loader2, Send } from 'lucide-react';
import { api, AuthUser, SubjectItem } from '../../services/api';

interface LeaveItem {
  id: string;
  student_name: string;
  roll_number: string;
  subject_code: string;
  start_date: string;
  end_date: string;
  reason: string;
  status: string;
}

export function LeaveRequestsView({ user }: { user: AuthUser }) {
  const [leaves, setLeaves] = useState<LeaveItem[]>([]);
  const [subjects, setSubjects] = useState<SubjectItem[]>([]);
  const [subjectCode, setSubjectCode] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [reason, setReason] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [lrRes, subjRes] = await Promise.all([
        api.get<LeaveItem[]>('/leave/requests'),
        api.get<SubjectItem[]>('/sessions/subjects'),
      ]);
      setLeaves(lrRes.data);
      setSubjects(subjRes.data);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setMessage(null);
    try {
      await api.post('/leave/request', {
        subject_code: subjectCode || null,
        start_date: new Date(startDate).toISOString(),
        end_date: new Date(endDate).toISOString(),
        reason,
      });
      setReason('');
      setMessage('Leave request submitted for instructor/authority review.');
      await loadData();
    } catch (err: any) {
      setMessage(err?.response?.data?.detail || 'Failed to submit leave request.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleReview = async (id: string, decision: 'APPROVED' | 'REJECTED') => {
    await api.post(`/leave/${id}/review`, { decision });
    await loadData();
  };

  return (
    <div className="space-y-6">
      {user.role === 'student' && (
        <form onSubmit={handleSubmit} className="glass-panel p-6 rounded-2xl space-y-4">
          <h2 className="text-base font-bold text-white flex items-center space-x-2">
            <Calendar className="w-5 h-5 text-indigo-400" />
            <span>Submit Academic / Medical Leave Request</span>
          </h2>
          {message && <div className="p-3 rounded-xl bg-indigo-950/60 border border-indigo-500/40 text-xs text-indigo-200">{message}</div>}

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <select value={subjectCode} onChange={(e) => setSubjectCode(e.target.value)} className="glass-input px-3 py-2 rounded-xl text-xs bg-slate-900">
              <option value="">All Enrolled Subjects</option>
              {subjects.map((s) => (
                <option key={s.id} value={s.code}>
                  {s.code} — {s.name}
                </option>
              ))}
            </select>
            <input type="date" required value={startDate} onChange={(e) => setStartDate(e.target.value)} className="glass-input px-3 py-2 rounded-xl text-xs" />
            <input type="date" required value={endDate} onChange={(e) => setEndDate(e.target.value)} className="glass-input px-3 py-2 rounded-xl text-xs" />
          </div>

          <textarea
            rows={2}
            required
            minLength={5}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason for leave (medical, institutional duty, etc.)"
            className="w-full glass-input p-3 rounded-xl text-xs"
          />

          <button type="submit" disabled={submitting} className="btn-primary px-5 py-2.5 rounded-xl text-xs font-semibold text-white flex items-center space-x-2">
            {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            <span>Submit Request</span>
          </button>
        </form>
      )}

      <div className="glass-panel p-6 rounded-2xl space-y-4">
        <h3 className="text-sm font-bold text-white">Leave Request History</h3>
        {loading ? (
          <Loader2 className="w-5 h-5 animate-spin text-indigo-400" />
        ) : leaves.length === 0 ? (
          <p className="text-xs text-slate-400">No leave requests recorded.</p>
        ) : (
          <div className="space-y-2.5">
            {leaves.map((lv) => (
              <div key={lv.id} className="p-4 rounded-xl glass-panel-subtle flex flex-wrap items-center justify-between gap-3 text-xs">
                <div>
                  <div className="font-bold text-white">
                    {lv.student_name} ({lv.roll_number}) • {lv.subject_code}
                  </div>
                  <div className="text-slate-300 mt-0.5">{lv.reason}</div>
                  <div className="text-[11px] text-slate-400 mt-0.5">
                    {lv.start_date.slice(0, 10)} → {lv.end_date.slice(0, 10)}
                  </div>
                </div>
                <div className="flex items-center space-x-2">
                  <span
                    className={`px-2.5 py-0.5 rounded text-[10px] font-bold ${
                      lv.status === 'APPROVED'
                        ? 'bg-emerald-500/20 text-emerald-300'
                        : lv.status === 'REJECTED'
                        ? 'bg-red-500/20 text-red-300'
                        : 'bg-amber-500/20 text-amber-300'
                    }`}
                  >
                    {lv.status}
                  </span>
                  {user.role !== 'student' && lv.status === 'PENDING' && (
                    <>
                      <button onClick={() => handleReview(lv.id, 'APPROVED')} className="p-1.5 rounded-lg bg-emerald-600/80 hover:bg-emerald-500 text-white" title="Approve">
                        <CheckCircle2 className="w-4 h-4" />
                      </button>
                      <button onClick={() => handleReview(lv.id, 'REJECTED')} className="p-1.5 rounded-lg bg-red-600/80 hover:bg-red-500 text-white" title="Reject">
                        <XCircle className="w-4 h-4" />
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
