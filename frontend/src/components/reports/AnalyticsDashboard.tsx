import { useState, useEffect, useCallback } from 'react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts';
import { ShieldAlert, Download, Loader2, Activity, Users, GraduationCap, UserCheck } from 'lucide-react';
import { api, getAccessToken } from '../../services/api';

interface AnalyticsPayload {
  kpis: {
    total_students: number;
    total_teachers: number;
    active_sessions: number;
    pending_biometric_approvals: number;
  };
  subject_breakdown: {
    subject_code: string;
    subject_name: string;
    sessions_held: number;
    present_records: number;
  }[];
  department_stats: { department: string; name: string; students: number }[];
  verification_events: { event: string; count: number }[];
  security_alerts: { id: string; event_type: string; details: string; ip_address: string | null; timestamp: string | null }[];
  audit_logs: { id: string; action: string; resource: string; details: string | null; timestamp: string | null }[];
}

export function AnalyticsDashboard() {
  const [data, setData] = useState<AnalyticsPayload | null>(null);
  const [loading, setLoading] = useState(true);

  const loadAnalytics = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<AnalyticsPayload>('/attendance/analytics');
      setData(res.data);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAnalytics();
  }, [loadAnalytics]);

  const downloadGlobalCsv = async () => {
    const token = getAccessToken();
    const res = await fetch('/api/v1/attendance/export', {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'smartpresence_attendance_export.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  if (loading) {
    return (
      <div className="glass-panel p-8 rounded-2xl flex justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-indigo-400" />
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="space-y-6">
      {/* KPI Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="glass-card-interactive p-5 rounded-2xl">
          <div className="text-xs text-slate-400 flex items-center space-x-1.5">
            <GraduationCap className="w-4 h-4 text-indigo-400" />
            <span>Total Students</span>
          </div>
          <div className="text-3xl font-extrabold text-white mt-2">{data.kpis.total_students}</div>
        </div>
        <div className="glass-card-interactive p-5 rounded-2xl">
          <div className="text-xs text-slate-400 flex items-center space-x-1.5">
            <Users className="w-4 h-4 text-cyan-400" />
            <span>Total Faculty</span>
          </div>
          <div className="text-3xl font-extrabold text-white mt-2">{data.kpis.total_teachers}</div>
        </div>
        <div className="glass-card-interactive p-5 rounded-2xl">
          <div className="text-xs text-slate-400 flex items-center space-x-1.5">
            <Activity className="w-4 h-4 text-emerald-400" />
            <span>Active Sessions</span>
          </div>
          <div className="text-3xl font-extrabold text-emerald-400 mt-2">{data.kpis.active_sessions}</div>
        </div>
        <div className="glass-card-interactive p-5 rounded-2xl">
          <div className="text-xs text-slate-400 flex items-center space-x-1.5">
            <UserCheck className="w-4 h-4 text-amber-400" />
            <span>Pending Biometrics</span>
          </div>
          <div className="text-3xl font-extrabold text-amber-400 mt-2">{data.kpis.pending_biometric_approvals}</div>
        </div>
      </div>

      {/* Subject Breakdown Chart + Security Events */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="glass-panel p-6 rounded-2xl space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-white">Subject Sessions &amp; Attendance Volume</h3>
            <button
              type="button"
              onClick={downloadGlobalCsv}
              className="btn-cyan px-3 py-1.5 rounded-lg text-[11px] font-semibold text-white flex items-center space-x-1.5"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Export All Records (CSV)</span>
            </button>
          </div>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.subject_breakdown}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="subject_code" stroke="#94A3B8" fontSize={11} />
                <YAxis stroke="#94A3B8" fontSize={11} allowDecimals={false} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#101B30',
                    border: '1px solid rgba(255,255,255,0.12)',
                    borderRadius: '12px',
                    color: '#F8FAFC',
                    fontSize: '12px',
                  }}
                />
                <Bar dataKey="sessions_held" name="Sessions Held" fill="#6366F1" radius={[6, 6, 0, 0]} />
                <Bar dataKey="present_records" name="Verified Records" fill="#22D3EE" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="glass-panel p-6 rounded-2xl space-y-4">
          <h3 className="text-sm font-bold text-white flex items-center space-x-2">
            <ShieldAlert className="w-4 h-4 text-amber-400" />
            <span>Security &amp; Verification Failure Alerts</span>
          </h3>
          {data.security_alerts.length === 0 ? (
            <div className="p-6 rounded-xl glass-panel-subtle text-center text-xs text-slate-400">
              No suspicious verification failures or spoofing attempts logged.
            </div>
          ) : (
            <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
              {data.security_alerts.map((al) => (
                <div key={al.id} className="p-3 rounded-xl bg-red-950/30 border border-red-500/20 text-xs space-y-1">
                  <div className="flex justify-between font-semibold text-red-300">
                    <span>{al.event_type}</span>
                    <span className="text-[10px] text-slate-400 font-mono">{al.ip_address || ''}</span>
                  </div>
                  <div className="text-[11px] text-slate-300">{al.details}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
