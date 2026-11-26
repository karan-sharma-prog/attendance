import { useState, useEffect, useCallback } from 'react';
import {
  ShieldCheck,
  QrCode,
  BarChart3,
  LogOut,
  Clock,
  Loader2,
  BellRing,
  WifiOff,
  Download,
} from 'lucide-react';
import {
  api,
  AuthUser,
  getAccessToken,
  setAuthTokens,
  SessionSummary,
  IndividualStudentReportResponse,
} from './services/api';
import { LoginView } from './components/auth/LoginView';
import { LiveSessionView } from './components/teacher/LiveSessionView';
import { QrScannerView } from './components/student/QrScannerView';
import { BiometricEnrollmentView } from './components/student/BiometricEnrollmentView';
import { BiometricApprovalsView } from './components/admin/BiometricApprovalsView';
import { AdminConsoleView } from './components/admin/AdminConsoleView';
import { LeaveRequestsView } from './components/student/LeaveRequestsView';
import { StudentTimetableView } from './components/student/StudentTimetableView';
import { ReportsAndMailerView } from './components/reports/ReportsAndMailerView';

interface NotificationItem {
  id: string;
  title: string;
  message: string;
  type: string;
  is_read: boolean;
  created_at: string | null;
}

export default function App() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [bootstrapping, setBootstrapping] = useState(true);
  const [pendingQrToken, setPendingQrToken] = useState<string | null>(() => {
    const params = new URLSearchParams(window.location.search);
    const urlToken = params.get('token');
    if (urlToken) {
      sessionStorage.setItem('sp_pending_qr_token', urlToken);
      window.history.replaceState({}, '', '/attend/verify');
      return urlToken;
    }
    return sessionStorage.getItem('sp_pending_qr_token');
  });
  const [activeTab, setActiveTab] = useState<'overview' | 'sessions' | 'reports' | 'enrollment' | 'leave' | 'admin'>('overview');
  const [activeSessions, setActiveSessions] = useState<SessionSummary[]>([]);
  const [studentReport, setStudentReport] = useState<IndividualStudentReportResponse | null>(null);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [showNotifs, setShowNotifs] = useState(false);
  const [isOnline, setIsOnline] = useState(typeof navigator !== 'undefined' ? navigator.onLine : true);
  const [installPrompt, setInstallPrompt] = useState<any>(null);

  useEffect(() => {
    const onOnline = () => setIsOnline(true);
    const onOffline = () => setIsOnline(false);
    const onInstallPrompt = (e: Event) => {
      e.preventDefault();
      setInstallPrompt(e);
    };
    window.addEventListener('online', onOnline);
    window.addEventListener('offline', onOffline);
    window.addEventListener('beforeinstallprompt', onInstallPrompt);
    return () => {
      window.removeEventListener('online', onOnline);
      window.removeEventListener('offline', onOffline);
      window.removeEventListener('beforeinstallprompt', onInstallPrompt);
    };
  }, []);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      setBootstrapping(false);
      return;
    }
    api
      .get('/auth/me')
      .then((res) => {
        setUser({
          user_id: res.data.id,
          email: res.data.email,
          full_name: res.data.full_name,
          role: res.data.role,
          student_id: res.data.student_id,
          teacher_id: res.data.teacher_id,
          enrollment_id: res.data.enrollment_id,
        });
      })
      .catch(() => {
        setAuthTokens(null, null);
      })
      .finally(() => setBootstrapping(false));
  }, []);

  const loadDashboardOverview = useCallback(async () => {
    if (!user) return;
    try {
      const [sessRes, notifRes] = await Promise.all([
        api.get<SessionSummary[]>('/sessions/active'),
        api.get<NotificationItem[]>('/notifications'),
      ]);
      setActiveSessions(sessRes.data);
      setNotifications(notifRes.data);
    } catch {
      setActiveSessions([]);
    }
    if (user.role === 'student') {
      try {
        const repRes = await api.get<IndividualStudentReportResponse>('/reports/student/me');
        setStudentReport(repRes.data);
      } catch {
        setStudentReport(null);
      }
    }
  }, [user]);

  useEffect(() => {
    if (user && activeTab === 'overview') {
      loadDashboardOverview();
    }
  }, [user, activeTab, loadDashboardOverview]);

  const handleMarkNotifRead = async (id: string) => {
    try {
      await api.post(`/notifications/${id}/read`);
      setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, is_read: true } : n)));
    } catch {
      // Ignore
    }
  };

  const handleInstallPwa = async () => {
    if (!installPrompt) return;
    installPrompt.prompt();
    await installPrompt.userChoice;
    setInstallPrompt(null);
  };

  useEffect(() => {
    if (user && pendingQrToken && user.role === 'student') {
      setActiveTab('sessions');
    }
  }, [user, pendingQrToken]);

  const handleTokenConsumed = useCallback(() => {
    sessionStorage.removeItem('sp_pending_qr_token');
    setPendingQrToken(null);
    if (window.location.pathname === '/attend/verify') {
      window.history.replaceState({}, '', '/');
    }
  }, []);

  const handleLogout = async () => {
    try {
      await api.post('/auth/logout', { refresh_token: sessionStorage.getItem('sp_refresh_token') });
    } catch {
      // Clear local session regardless
    }
    setAuthTokens(null, null);
    setUser(null);
    setStudentReport(null);
    setActiveSessions([]);
    setNotifications([]);
    setActiveTab('overview');
  };

  if (bootstrapping) {
    return (
      <div className="min-h-screen bg-[#080F1F] flex items-center justify-center text-slate-300 space-x-2">
        <Loader2 className="w-5 h-5 animate-spin text-indigo-400" />
        <span className="text-xs">Verifying session with SmartPresence backend...</span>
      </div>
    );
  }

  if (!user) {
    return (
      <LoginView
        pendingQrDetected={Boolean(pendingQrToken)}
        onLoginSuccess={(u) => {
          setUser(u);
          if (pendingQrToken && u.role === 'student') {
            setActiveTab('sessions');
          }
        }}
      />
    );
  }

  const unreadCount = notifications.filter((n) => !n.is_read).length;
  const initials = user.full_name
    .split(' ')
    .map((p) => p[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();

  return (
    <div className="min-h-screen bg-[#080F1F] text-[#F8FAFC] flex flex-col relative overflow-hidden">
      <div className="absolute top-[-10%] left-[-10%] w-[500px] h-[500px] bg-indigo-600/15 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[500px] h-[500px] bg-cyan-500/10 rounded-full blur-[140px] pointer-events-none" />

      {!isOnline && (
        <div className="bg-red-950/90 border-b border-red-500/50 px-4 py-2 text-xs text-red-200 flex items-center justify-center space-x-2 z-50">
          <WifiOff className="w-4 h-4 text-red-400" />
          <span>Offline: Attendance marking requires a live backend connection. Reconnect to verify attendance.</span>
        </div>
      )}

      {/* Top Navigation */}
      <header className="sticky top-0 z-50 glass-panel border-b border-white/10 px-6 py-4 flex items-center justify-between gap-4">
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-500 to-cyan-400 p-[1.5px] flex items-center justify-center shadow-glass-glow">
            <div className="w-full h-full bg-[#080F1F] rounded-[10px] flex items-center justify-center">
              <ShieldCheck className="w-5 h-5 text-cyan-400" />
            </div>
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="font-extrabold text-lg tracking-tight bg-gradient-to-r from-white via-slate-100 to-slate-400 bg-clip-text text-transparent">
                SmartPresence
              </span>
              <span className="liquid-badge text-cyan-300 text-[10px] font-semibold px-2 py-0.5 rounded-full uppercase tracking-wider">
                {user.role}
              </span>
            </div>
            <p className="text-xs text-slate-400 hidden sm:block">Dynamic QR • Liveness • ArcFace Recognition</p>
          </div>
        </div>

        <div className="flex items-center space-x-3 relative">
          {installPrompt && (
            <button
              onClick={handleInstallPwa}
              className="px-3 py-1.5 rounded-xl bg-cyan-600/80 hover:bg-cyan-500 text-xs font-semibold text-white flex items-center space-x-1.5"
            >
              <Download className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Install App</span>
            </button>
          )}

          <button
            onClick={() => setShowNotifs((v) => !v)}
            className="relative p-2 rounded-xl glass-panel-subtle hover:bg-white/10 text-slate-300 transition"
          >
            <BellRing className="w-4 h-4" />
            {unreadCount > 0 && <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-indigo-500 rounded-full animate-pulse" />}
          </button>

          {showNotifs && (
            <div className="absolute right-0 top-12 w-80 glass-panel rounded-2xl p-4 space-y-2 z-50 border border-white/15">
              <div className="text-xs font-bold text-white border-b border-white/10 pb-2">Notifications ({unreadCount} unread)</div>
              {notifications.length === 0 ? (
                <div className="text-xs text-slate-400 py-3 text-center">No notifications.</div>
              ) : (
                <div className="max-h-64 overflow-y-auto space-y-2">
                  {notifications.map((n) => (
                    <div
                      key={n.id}
                      onClick={() => handleMarkNotifRead(n.id)}
                      className={`p-2.5 rounded-xl text-xs cursor-pointer ${n.is_read ? 'bg-white/[0.02] text-slate-400' : 'bg-indigo-950/60 border border-indigo-500/30 text-white'}`}
                    >
                      <div className="font-semibold">{n.title}</div>
                      <div className="text-[11px] opacity-80 mt-0.5">{n.message}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="flex items-center space-x-3 pr-3 border-r border-white/10">
            <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-indigo-500 to-purple-600 flex items-center justify-center text-xs font-bold">
              {initials}
            </div>
            <div className="hidden md:block text-left">
              <div className="text-xs font-semibold leading-tight">{user.full_name}</div>
              <div className="text-[10px] text-slate-400">{user.email}</div>
            </div>
          </div>

          <button
            onClick={handleLogout}
            className="px-3 py-1.5 rounded-xl glass-panel-subtle hover:bg-white/10 text-xs text-slate-300 flex items-center space-x-1.5 transition"
          >
            <LogOut className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Logout</span>
          </button>
        </div>
      </header>

      {/* Main Content Layout */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-6 space-y-6 relative z-10">
        <div className="flex flex-wrap gap-6 border-b border-white/10 pb-3">
          {[
            { id: 'overview', label: 'Dashboard Overview' },
            { id: 'sessions', label: user.role === 'student' ? 'Scan Attendance QR' : 'Live QR & Sessions' },
            { id: 'reports', label: user.role === 'student' ? 'My Attendance Report' : 'Analytics, Reports & Mailer' },
            { id: 'enrollment', label: user.role === 'admin' ? 'Biometric Approvals' : 'Biometric Enrollment' },
            { id: 'leave', label: 'Leave Requests' },
            ...(user.role === 'admin' ? [{ id: 'admin', label: 'Admin Console' }] : []),
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`pb-2 px-1 text-sm font-medium transition-all relative ${
                activeTab === tab.id ? 'text-indigo-400' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {tab.label}
              {activeTab === tab.id && <span className="absolute bottom-[-13px] left-0 right-0 h-[2px] bg-indigo-500" />}
            </button>
          ))}
        </div>

        {/* OVERVIEW */}
        {activeTab === 'overview' && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              <div className="glass-card-interactive p-5 rounded-2xl">
                <div className="text-slate-400 text-xs font-medium">Active Attendance Sessions Now</div>
                <div className="text-3xl font-extrabold text-white mt-2">{activeSessions.length}</div>
                <div className="text-xs text-slate-400 mt-2 flex items-center space-x-1">
                  <Clock className="w-3.5 h-3.5 text-cyan-400" />
                  <span>Synced with Neon PostgreSQL</span>
                </div>
              </div>

              {user.role === 'student' && (
                <div className="glass-card-interactive p-5 rounded-2xl">
                  <div className="text-slate-400 text-xs font-medium">Overall Attendance</div>
                  <div className="text-3xl font-extrabold text-white mt-2">
                    {studentReport ? `${studentReport.overall_percentage}%` : '—'}
                  </div>
                  <div className="text-xs text-slate-400 mt-2">
                    {studentReport ? `${studentReport.courses.length} enrolled subjects` : 'Loading academic enrollment...'}
                  </div>
                </div>
              )}

              <div className="glass-card-interactive p-5 rounded-2xl flex flex-col justify-between">
                <div className="text-slate-400 text-xs font-medium">Quick Action</div>
                <button
                  onClick={() => setActiveTab('sessions')}
                  className="w-full mt-3 py-2.5 px-4 rounded-xl btn-primary text-xs font-semibold flex items-center justify-center space-x-2 text-white"
                >
                  <QrCode className="w-4 h-4" />
                  <span>{user.role === 'student' ? 'Open QR Scanner' : 'Manage Attendance Sessions'}</span>
                </button>
              </div>
            </div>

            <div className="glass-panel p-6 rounded-2xl space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-white flex items-center space-x-2">
                  <BarChart3 className="w-4 h-4 text-indigo-400" />
                  <span>Active Classroom Sessions</span>
                </h3>
                <button onClick={loadDashboardOverview} className="text-xs text-cyan-300 hover:underline">
                  Refresh
                </button>
              </div>

              {activeSessions.length === 0 ? (
                <div className="p-6 rounded-xl glass-panel-subtle text-center text-xs text-slate-400">
                  No active attendance sessions are currently open.
                </div>
              ) : (
                <div className="space-y-2.5">
                  {activeSessions.map((s) => (
                    <div key={s.id} className="p-4 rounded-xl glass-panel-subtle flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <div className="text-xs font-bold text-white">
                          {s.subject_code}: {s.subject_name}
                        </div>
                        <div className="text-[11px] text-slate-400 mt-0.5">
                          {s.classroom || 'Classroom'} • Instructor: {s.teacher_name} • Status: {s.status}
                        </div>
                      </div>
                      <button onClick={() => setActiveTab('sessions')} className="px-3 py-1.5 rounded-lg bg-indigo-600/80 hover:bg-indigo-500 text-xs font-medium text-white">
                        {user.role === 'student' ? 'Scan QR' : 'Open Live Monitor'}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {user.role === 'student' && (
              <StudentTimetableView
                activeSessions={activeSessions}
                onScanClick={() => setActiveTab('sessions')}
              />
            )}
          </div>
        )}

        {activeTab === 'sessions' &&
          (user.role === 'student' ? (
            <QrScannerView
              initialToken={pendingQrToken}
              onTokenConsumed={handleTokenConsumed}
              onGoToEnrollment={() => setActiveTab('enrollment')}
            />
          ) : (
            <LiveSessionView />
          ))}
        {activeTab === 'reports' && <ReportsAndMailerView user={user} />}
        {activeTab === 'enrollment' &&
          (user.role === 'admin' ? (
            <BiometricApprovalsView />
          ) : user.role === 'student' ? (
            <BiometricEnrollmentView />
          ) : (
            <div className="glass-panel p-8 rounded-2xl text-center text-xs text-slate-400">
              Biometric profile enrollment is managed by Students and reviewed by Institutional Administrators.
            </div>
          ))}
        {activeTab === 'leave' && <LeaveRequestsView user={user} />}
        {activeTab === 'admin' && user.role === 'admin' && <AdminConsoleView />}
      </main>
    </div>
  );
}
