import { useState, useEffect, useCallback, FormEvent } from 'react';
import { Settings, Users, BookOpen, PlusCircle, Loader2 } from 'lucide-react';
import { api } from '../../services/api';

interface AdminOverview {
  users: { id: string; email: string; full_name: string; enrollment_id: string | null; role: string; is_active: boolean }[];
  subjects: { id: string; code: string; name: string; credits: number }[];
  departments: { id: string; code: string; name: string }[];
  settings: { key: string; value: string; description: string | null }[];
}

export function AdminConsoleView() {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [subjCode, setSubjCode] = useState('');
  const [subjName, setSubjName] = useState('');
  const [thresholdVal, setThresholdVal] = useState('75.0');
  const [feedback, setFeedback] = useState<string | null>(null);

  const loadOverview = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<AdminOverview>('/admin/overview');
      setOverview(res.data);
      const th = res.data.settings.find((s) => s.key === 'ATTENDANCE_WARNING_THRESHOLD_PERCENT');
      if (th) setThresholdVal(th.value);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadOverview();
  }, [loadOverview]);

  const handleAddSubject = async (e: FormEvent) => {
    e.preventDefault();
    setFeedback(null);
    try {
      await api.post('/admin/subjects', { code: subjCode, name: subjName, credits: 3, department_code: 'CSE' });
      setSubjCode('');
      setSubjName('');
      setFeedback('Subject created and persisted on Neon PostgreSQL.');
      await loadOverview();
    } catch (err: any) {
      setFeedback(err?.response?.data?.detail || 'Could not create subject.');
    }
  };

  const handleSavePolicy = async () => {
    await api.put('/admin/settings', {
      key: 'ATTENDANCE_WARNING_THRESHOLD_PERCENT',
      value: thresholdVal,
      description: 'Minimum attendance percentage before automated warning alerts',
    });
    setFeedback('Institutional policy threshold updated.');
    await loadOverview();
  };

  if (loading) {
    return (
      <div className="glass-panel p-10 rounded-2xl flex justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-indigo-400" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {feedback && <div className="p-3.5 rounded-xl bg-indigo-950/60 border border-indigo-500/40 text-xs text-indigo-200">{feedback}</div>}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Institutional Policy Settings */}
        <div className="glass-panel p-6 rounded-2xl space-y-4">
          <h3 className="text-sm font-bold text-white flex items-center space-x-2">
            <Settings className="w-4 h-4 text-cyan-400" />
            <span>Institutional Verification Policies</span>
          </h3>
          <div className="flex items-center space-x-3">
            <label className="text-xs text-slate-300">Low-Attendance Alert Threshold (%):</label>
            <input type="text" value={thresholdVal} onChange={(e) => setThresholdVal(e.target.value)} className="w-24 glass-input px-3 py-1.5 rounded-xl text-xs" />
            <button onClick={handleSavePolicy} className="btn-primary px-4 py-2 rounded-xl text-xs font-semibold text-white">
              Save Policy
            </button>
          </div>
        </div>

        {/* Add Subject */}
        <form onSubmit={handleAddSubject} className="glass-panel p-6 rounded-2xl space-y-4">
          <h3 className="text-sm font-bold text-white flex items-center space-x-2">
            <BookOpen className="w-4 h-4 text-indigo-400" />
            <span>Add Academic Subject (CSE)</span>
          </h3>
          <div className="flex flex-wrap gap-2">
            <input required placeholder="Code (e.g. CS-409)" value={subjCode} onChange={(e) => setSubjCode(e.target.value)} className="glass-input px-3 py-2 rounded-xl text-xs w-36" />
            <input required placeholder="Subject Title" value={subjName} onChange={(e) => setSubjName(e.target.value)} className="glass-input px-3 py-2 rounded-xl text-xs flex-1" />
            <button type="submit" className="btn-cyan px-4 py-2 rounded-xl text-xs font-semibold text-white flex items-center space-x-1">
              <PlusCircle className="w-3.5 h-3.5" />
              <span>Add</span>
            </button>
          </div>
        </form>
      </div>

      {/* Institutional Users Directory */}
      <div className="glass-panel p-6 rounded-2xl space-y-4">
        <h3 className="text-sm font-bold text-white flex items-center space-x-2">
          <Users className="w-4 h-4 text-indigo-400" />
          <span>Registered Institutional Accounts ({overview?.users.length || 0})</span>
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {overview?.users.map((u) => (
            <div key={u.id} className="p-3.5 rounded-xl glass-panel-subtle text-xs space-y-1">
              <div className="flex justify-between items-center">
                <span className="font-bold text-white">{u.full_name}</span>
                <span className="px-2 py-0.5 rounded bg-indigo-500/20 text-cyan-300 text-[10px] uppercase">{u.role}</span>
              </div>
              <div className="text-slate-400 truncate">{u.email}</div>
              <div className="text-[10px] font-mono text-slate-500">{u.enrollment_id || u.id.slice(0, 8)}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
