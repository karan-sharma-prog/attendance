import { useState, useEffect, useCallback } from 'react';
import { BarChart3, Mail, AlertCircle, Send, Download, Search, Loader2, CheckCircle2 } from 'lucide-react';
import {
  api,
  AuthUser,
  IndividualStudentReportResponse,
  LowAttendanceStudentItem,
} from '../../services/api';
import { AnalyticsDashboard } from './AnalyticsDashboard';

interface ReportsProps {
  user: AuthUser;
}

export function ReportsAndMailerView({ user }: ReportsProps) {
  const [rollLookup, setRollLookup] = useState('CS2024-8841');
  const [report, setReport] = useState<IndividualStudentReportResponse | null>(null);
  const [lowStudents, setLowStudents] = useState<LowAttendanceStudentItem[]>([]);
  const [loadingReport, setLoadingReport] = useState(false);
  const [sendingEmail, setSendingEmail] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadReport = useCallback(
    async (identifier?: string) => {
      setLoadingReport(true);
      setError(null);
      try {
        const endpoint =
          user.role === 'student' ? '/reports/student/me' : `/reports/student/${encodeURIComponent(identifier || rollLookup)}`;
        const res = await api.get<IndividualStudentReportResponse>(endpoint);
        setReport(res.data);
      } catch (err: any) {
        setReport(null);
        setError(err?.response?.data?.detail || 'Could not load student attendance report.');
      } finally {
        setLoadingReport(false);
      }
    },
    [user.role, rollLookup]
  );

  const loadLowAttendance = useCallback(async () => {
    if (user.role === 'student') return;
    try {
      const res = await api.get<LowAttendanceStudentItem[]>('/reports/low-attendance?threshold=75');
      setLowStudents(res.data);
    } catch {
      // Ignore if unauthorized
    }
  }, [user.role]);

  useEffect(() => {
    loadReport();
    loadLowAttendance();
  }, [loadReport, loadLowAttendance]);

  const handleDispatchWarningEmail = async (studentId?: string) => {
    setSendingEmail(studentId || 'ALL');
    setBanner(null);
    setError(null);
    try {
      const res = await api.post('/reports/send-low-attendance-emails', {
        student_ids: studentId ? [studentId] : undefined,
        threshold: 75.0,
        custom_message: 'Please attend upcoming sessions and contact your faculty advisor.',
      });
      const mode = res.data.smtp_configured ? 'SMTP SSL Dispatched' : 'Logged (SMTP_USER/PASSWORD unconfigured in .env)';
      setBanner(`Processed ${res.data.total_dispatched} low-attendance alert(s) • Mode: ${mode}`);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to dispatch low-attendance emails.');
    } finally {
      setSendingEmail(null);
    }
  };

  const exportCsv = () => {
    if (!report) return;
    const rows = [
      ['Roll Number', 'Student Name', 'Subject Code', 'Subject Name', 'Attended', 'Total Classes', 'Percentage', 'At Risk'],
      ...report.courses.map((c) => [
        report.roll_number,
        report.student_name,
        c.subject_code,
        c.subject_name,
        String(c.attended_classes),
        String(c.total_classes),
        `${c.attendance_percentage}%`,
        c.is_at_risk ? 'YES' : 'NO',
      ]),
    ];
    const csv = rows.map((r) => r.map((v) => `"${v.replaceAll('"', '""')}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `attendance_report_${report.roll_number}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      {banner && (
        <div className="p-3.5 rounded-xl bg-indigo-950/70 border border-indigo-500/40 text-xs text-indigo-200 flex items-center space-x-2">
          <Mail className="w-4 h-4 text-cyan-400 shrink-0" />
          <span>{banner}</span>
        </div>
      )}

      {error && (
        <div className="p-3.5 rounded-xl bg-red-950/60 border border-red-500/40 text-xs text-red-200 flex items-center space-x-2">
          <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Analytics Charts & Security Alerts (Teachers & Admins) */}
      {user.role !== 'student' && <AnalyticsDashboard />}

      {/* Low-Attendance Monitoring & Mailer (Teachers & Admins) */}
      {user.role !== 'student' && (
        <div className="glass-panel p-6 rounded-2xl space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-base font-bold text-white flex items-center space-x-2">
                <AlertCircle className="w-5 h-5 text-amber-400" />
                <span>Low-Attendance Monitoring &amp; Direct Email Alerts (&lt; 75%)</span>
              </h2>
              <p className="text-xs text-slate-400 mt-1">
                Queried live from Neon PostgreSQL attendance records.
              </p>
            </div>
            {lowStudents.length > 0 && (
              <button
                type="button"
                onClick={() => handleDispatchWarningEmail()}
                disabled={sendingEmail === 'ALL'}
                className="btn-primary px-4 py-2 rounded-xl text-xs font-semibold text-white flex items-center space-x-1.5"
              >
                {sendingEmail === 'ALL' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                <span>Email All At-Risk Students</span>
              </button>
            )}
          </div>

          {lowStudents.length === 0 ? (
            <div className="p-4 rounded-xl glass-panel-subtle text-xs text-slate-400 flex items-center space-x-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <span>No students currently fall below the 75% threshold in held sessions.</span>
            </div>
          ) : (
            <div className="space-y-2.5">
              {lowStudents.map((stu, idx) => (
                <div
                  key={`${stu.student_id}-${idx}`}
                  className="p-4 rounded-xl glass-card-interactive flex flex-col sm:flex-row sm:items-center justify-between gap-3"
                >
                  <div>
                    <div className="text-xs font-bold text-white flex items-center space-x-2">
                      <span>{stu.student_name}</span>
                      <span className="text-[10px] text-slate-400 font-mono">({stu.roll_number})</span>
                      <span className="text-[10px] bg-red-950/60 text-red-400 px-2 py-0.5 rounded border border-red-500/30 font-semibold">
                        {stu.attendance_percentage}% ({stu.attended_classes}/{stu.total_classes})
                      </span>
                    </div>
                    <div className="text-[11px] text-slate-400 mt-0.5">{stu.subject_name}</div>
                  </div>

                  <button
                    type="button"
                    onClick={() => handleDispatchWarningEmail(stu.student_id)}
                    disabled={sendingEmail === stu.student_id}
                    className="py-1.5 px-3 rounded-lg bg-indigo-600/80 hover:bg-indigo-500 text-xs font-medium text-white flex items-center space-x-1.5 w-fit"
                  >
                    <Send className="w-3.5 h-3.5" />
                    <span>Send Warning Email</span>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Individual Student Attendance Report */}
      <div className="glass-panel p-6 rounded-2xl space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h3 className="text-base font-bold text-white flex items-center space-x-2">
            <BarChart3 className="w-5 h-5 text-indigo-400" />
            <span>Individual Student Attendance Report</span>
          </h3>

          <div className="flex flex-wrap items-center gap-2">
            {user.role !== 'student' && (
              <>
                <input
                  type="text"
                  value={rollLookup}
                  onChange={(e) => setRollLookup(e.target.value)}
                  placeholder="Roll Number (e.g. CS2024-8841)"
                  className="glass-input px-3 py-2 rounded-xl text-xs"
                />
                <button
                  type="button"
                  onClick={() => loadReport(rollLookup)}
                  className="btn-primary px-3.5 py-2 rounded-xl text-xs font-semibold text-white flex items-center space-x-1.5"
                >
                  <Search className="w-3.5 h-3.5" />
                  <span>Lookup</span>
                </button>
              </>
            )}
            {report && (
              <button
                type="button"
                onClick={exportCsv}
                className="btn-cyan px-3.5 py-2 rounded-xl text-xs font-semibold text-white flex items-center space-x-1.5"
              >
                <Download className="w-3.5 h-3.5" />
                <span>Export CSV</span>
              </button>
            )}
          </div>
        </div>

        {loadingReport ? (
          <div className="py-8 flex justify-center">
            <Loader2 className="w-6 h-6 animate-spin text-indigo-400" />
          </div>
        ) : report ? (
          <div className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="p-4 rounded-xl glass-panel-subtle">
                <div className="text-[11px] text-slate-400">Student</div>
                <div className="text-sm font-bold text-white mt-1">{report.student_name}</div>
                <div className="text-[11px] text-slate-400 font-mono">{report.roll_number}</div>
              </div>
              <div className="p-4 rounded-xl glass-panel-subtle">
                <div className="text-[11px] text-slate-400">Department</div>
                <div className="text-sm font-bold text-white mt-1">{report.department}</div>
              </div>
              <div className="p-4 rounded-xl glass-panel-subtle">
                <div className="text-[11px] text-slate-400">Overall Attendance</div>
                <div className="text-2xl font-extrabold text-white mt-1">
                  {report.overall_percentage}%
                  {report.is_overall_at_risk && (
                    <span className="ml-2 text-xs text-red-400 font-semibold">AT RISK</span>
                  )}
                </div>
              </div>
            </div>

            {report.courses.length === 0 ? (
              <p className="text-xs text-slate-400 text-center py-4">No enrolled courses found.</p>
            ) : (
              <div className="space-y-2.5">
                {report.courses.map((course) => (
                  <div
                    key={course.subject_id}
                    className="p-4 rounded-xl glass-panel-subtle flex items-center justify-between"
                  >
                    <div>
                      <div className="text-xs font-bold text-white">
                        {course.subject_code}: {course.subject_name}
                      </div>
                      <div className="text-[11px] text-slate-400 mt-0.5">
                        Attended {course.attended_classes} / {course.total_classes} held sessions
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-sm font-extrabold text-white">
                        {course.total_classes === 0 ? 'No sessions yet' : `${course.attendance_percentage}%`}
                      </div>
                      {course.is_at_risk && (
                        <span className="text-[10px] text-red-400 font-semibold">Below 75%</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
