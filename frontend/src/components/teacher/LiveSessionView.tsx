import { useState, useEffect, useCallback, useRef } from 'react';
import {
  QrCode,
  Play,
  Pause,
  PlusCircle,
  XCircle,
  Clock,
  Users,
  Loader2,
  Maximize2,
  Minimize2,
  AlertTriangle,
  Copy,
  Check,
} from 'lucide-react';
import {
  api,
  getAccessToken,
  SessionSummary,
  SessionDetailResponse,
  DynamicQRResponse,
  SubjectItem,
} from '../../services/api';
import { TimetableManager } from './TimetableManager';

export function LiveSessionView() {
  const [subjects, setSubjects] = useState<SubjectItem[]>([]);
  const [activeSessions, setActiveSessions] = useState<SessionSummary[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [sessionDetail, setSessionDetail] = useState<SessionDetailResponse | null>(null);
  const [qrData, setQrData] = useState<DynamicQRResponse | null>(null);
  const [qrCountdown, setQrCountdown] = useState<number>(0);
  const [sessionCountdown, setSessionCountdown] = useState<string>('--:--');
  const [presentationMode, setPresentationMode] = useState(false);
  const [copiedToken, setCopiedToken] = useState(false);

  // Form states
  const [subjectCode, setSubjectCode] = useState('CS-401');
  const [durationMinutes, setDurationMinutes] = useState<number>(5);
  const [customDuration, setCustomDuration] = useState<number>(15);
  const [useCustomDuration, setUseCustomDuration] = useState(false);
  const [refreshInterval, setRefreshInterval] = useState<number>(8);
  const [classroom, setClassroom] = useState('Hall 302');
  const [geofenceRequired, setGeofenceRequired] = useState(false);
  const [geofenceLat, setGeofenceLat] = useState<string>('');
  const [geofenceLng, setGeofenceLng] = useState<string>('');
  const [geofenceRadius, setGeofenceRadius] = useState<number>(150);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);

  const fetchInitialData = useCallback(async () => {
    try {
      const [subjRes, sessRes] = await Promise.all([
        api.get<SubjectItem[]>('/sessions/subjects'),
        api.get<SessionSummary[]>('/sessions/active'),
      ]);
      setSubjects(subjRes.data);
      if (subjRes.data.length > 0 && !subjRes.data.some((s) => s.code === subjectCode)) {
        setSubjectCode(subjRes.data[0].code);
      }
      setActiveSessions(sessRes.data);
      if (sessRes.data.length > 0 && !selectedSessionId) {
        setSelectedSessionId(sessRes.data[0].id);
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to load sessions from backend.');
    }
  }, [selectedSessionId, subjectCode]);

  const fetchSessionDetail = useCallback(async (sid: string) => {
    try {
      const res = await api.get<SessionDetailResponse>(`/sessions/${sid}`);
      setSessionDetail(res.data);
    } catch {
      // Session might have closed
    }
  }, []);

  const fetchDynamicQR = useCallback(async (sid: string) => {
    try {
      const res = await api.get<DynamicQRResponse>(`/sessions/${sid}/qr`);
      setQrData(res.data);
      setQrCountdown(res.data.refresh_interval);
    } catch (err: any) {
      setQrData(null);
      if (err?.response?.status === 400) {
        // Paused or expired
        fetchSessionDetail(sid);
      }
    }
  }, [fetchSessionDetail]);

  useEffect(() => {
    fetchInitialData();
  }, [fetchInitialData]);

  // Poll QR every refresh_interval seconds & connect WebSocket when a session is selected
  useEffect(() => {
    if (!selectedSessionId) {
      setSessionDetail(null);
      setQrData(null);
      return;
    }

    fetchSessionDetail(selectedSessionId);
    fetchDynamicQR(selectedSessionId);

    const token = getAccessToken();
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/attendance/${selectedSessionId}?token=${encodeURIComponent(token || '')}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = () => {
      fetchSessionDetail(selectedSessionId);
      fetchInitialData();
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [selectedSessionId, fetchSessionDetail, fetchDynamicQR, fetchInitialData]);

  // QR Refresh & Countdown timers
  useEffect(() => {
    if (!selectedSessionId || !sessionDetail || sessionDetail.is_paused || !sessionDetail.is_active) {
      return;
    }

    const qrTimer = setInterval(() => {
      setQrCountdown((prev) => {
        if (prev <= 1) {
          fetchDynamicQR(selectedSessionId);
          return sessionDetail.qr_refresh_interval;
        }
        return prev - 1;
      });
    }, 1000);

    const winTimer = setInterval(() => {
      const endMs = new Date(sessionDetail.end_time).getTime();
      const diffSec = Math.max(0, Math.floor((endMs - Date.now()) / 1000));
      const m = Math.floor(diffSec / 60);
      const s = diffSec % 60;
      setSessionCountdown(`${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`);
      if (diffSec === 0) {
        fetchInitialData();
        fetchSessionDetail(selectedSessionId);
      }
    }, 1000);

    return () => {
      clearInterval(qrTimer);
      clearInterval(winTimer);
    };
  }, [selectedSessionId, sessionDetail, fetchDynamicQR, fetchInitialData, fetchSessionDetail]);

  const handleCaptureTeacherLocation = () => {
    if (!navigator.geolocation) {
      setError('Geolocation API unavailable in this browser.');
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setGeofenceLat(pos.coords.latitude.toFixed(6));
        setGeofenceLng(pos.coords.longitude.toFixed(6));
        setGeofenceRequired(true);
      },
      (err) => setError(`Could not obtain location: ${err.message}`),
      { enableHighAccuracy: true, timeout: 8000 }
    );
  };

  const handleCreateSession = async () => {
    setError(null);
    setCreating(true);
    try {
      const dur = useCustomDuration ? customDuration : durationMinutes;
      const res = await api.post<SessionSummary>('/sessions/create', {
        subject_code: subjectCode,
        duration_minutes: dur,
        mode: 'MANUAL',
        qr_refresh_interval: refreshInterval,
        classroom,
        geofence_required: geofenceRequired,
        geofence_lat: geofenceRequired && geofenceLat ? Number(geofenceLat) : null,
        geofence_lng: geofenceRequired && geofenceLng ? Number(geofenceLng) : null,
        geofence_radius_meters: geofenceRadius,
      });
      await fetchInitialData();
      setSelectedSessionId(res.data.id);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to create attendance session.');
    } finally {
      setCreating(false);
    }
  };

  const handleSessionAction = async (action: 'pause' | 'start' | 'close' | 'extend', extraMinutes?: number) => {
    if (!selectedSessionId) return;
    setError(null);
    try {
      if (action === 'extend') {
        await api.post(`/sessions/${selectedSessionId}/extend`, { additional_minutes: extraMinutes || 5 });
      } else {
        await api.post(`/sessions/${selectedSessionId}/${action}`);
      }
      await fetchSessionDetail(selectedSessionId);
      await fetchInitialData();
      if (action !== 'close' && action !== 'pause') {
        await fetchDynamicQR(selectedSessionId);
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail || `Failed to ${action} session.`);
    }
  };

  const copyQrTokenForTest = () => {
    if (!qrData) return;
    navigator.clipboard.writeText(qrData.qr_url || qrData.qr_token);
    setCopiedToken(true);
    setTimeout(() => setCopiedToken(false), 2000);
  };

  return (
    <div className="space-y-6">
      {error && (
        <div className="p-3.5 rounded-xl bg-red-950/60 border border-red-500/40 text-xs text-red-200 flex items-center space-x-2">
          <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Session Creation + Timetable Upload Panel (hidden in presentation mode) */}
      {!presentationMode && (
        <>
          <div className="glass-panel p-6 rounded-2xl space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-bold text-white">Create Attendance Session (Manual Mode)</h2>
                <p className="text-xs text-slate-400">
                  Server-synchronized attendance window with rotating HMAC-SHA256 HTTPS QR links.
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
              <div className="space-y-1">
                <label className="text-[11px] text-slate-400">Subject</label>
                <select
                  value={subjectCode}
                  onChange={(e) => setSubjectCode(e.target.value)}
                  className="w-full glass-input px-3 py-2 rounded-xl text-xs bg-slate-900"
                >
                  {subjects.map((s) => (
                    <option key={s.id} value={s.code}>
                      {s.code} — {s.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-[11px] text-slate-400">Classroom</label>
                <input
                  type="text"
                  value={classroom}
                  onChange={(e) => setClassroom(e.target.value)}
                  className="w-full glass-input px-3 py-2 rounded-xl text-xs"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[11px] text-slate-400">Window Duration</label>
                <div className="flex space-x-1">
                  {[2, 3, 5, 10].map((m) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => {
                        setUseCustomDuration(false);
                        setDurationMinutes(m);
                      }}
                      className={`flex-1 py-2 rounded-lg text-xs font-semibold transition ${
                        !useCustomDuration && durationMinutes === m
                          ? 'bg-indigo-600 text-white'
                          : 'glass-panel-subtle text-slate-400 hover:text-white'
                      }`}
                    >
                      {m}m
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={() => setUseCustomDuration(true)}
                    className={`px-2 py-2 rounded-lg text-xs font-semibold transition ${
                      useCustomDuration ? 'bg-indigo-600 text-white' : 'glass-panel-subtle text-slate-400'
                    }`}
                  >
                    Custom
                  </button>
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-[11px] text-slate-400">QR Rotation (5–10s)</label>
                <select
                  value={refreshInterval}
                  onChange={(e) => setRefreshInterval(Number(e.target.value))}
                  className="w-full glass-input px-3 py-2 rounded-xl text-xs bg-slate-900"
                >
                  <option value={5}>Every 5 seconds</option>
                  <option value={8}>Every 8 seconds</option>
                  <option value={10}>Every 10 seconds</option>
                </select>
              </div>
            </div>

            {useCustomDuration && (
              <div className="flex items-center space-x-3">
                <label className="text-xs text-slate-300">Custom Duration (minutes):</label>
                <input
                  type="number"
                  min={1}
                  max={180}
                  value={customDuration}
                  onChange={(e) => setCustomDuration(Number(e.target.value))}
                  className="w-24 glass-input px-3 py-1.5 rounded-lg text-xs"
                />
              </div>
            )}

            <div className="p-3 rounded-xl glass-panel-subtle space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <label className="flex items-center space-x-2 text-xs text-slate-200 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={geofenceRequired}
                    onChange={(e) => setGeofenceRequired(e.target.checked)}
                    className="accent-indigo-500"
                  />
                  <span>Require Classroom GPS Geofence</span>
                </label>
                <button
                  type="button"
                  onClick={handleCaptureTeacherLocation}
                  className="text-[11px] text-cyan-300 hover:underline"
                >
                  Use My Current Location
                </button>
              </div>
              {geofenceRequired && (
                <div className="grid grid-cols-3 gap-2 pt-1">
                  <input
                    type="text"
                    placeholder="Latitude"
                    value={geofenceLat}
                    onChange={(e) => setGeofenceLat(e.target.value)}
                    className="glass-input px-2.5 py-1.5 rounded-lg text-xs"
                  />
                  <input
                    type="text"
                    placeholder="Longitude"
                    value={geofenceLng}
                    onChange={(e) => setGeofenceLng(e.target.value)}
                    className="glass-input px-2.5 py-1.5 rounded-lg text-xs"
                  />
                  <input
                    type="number"
                    min={10}
                    max={5000}
                    placeholder="Radius (m)"
                    value={geofenceRadius}
                    onChange={(e) => setGeofenceRadius(Number(e.target.value))}
                    className="glass-input px-2.5 py-1.5 rounded-lg text-xs"
                  />
                </div>
              )}
            </div>

            <button
              type="button"
              onClick={handleCreateSession}
              disabled={creating}
              className="btn-primary px-5 py-2.5 rounded-xl text-xs font-semibold text-white flex items-center space-x-2"
            >
              {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              <span>Start Live Attendance Session</span>
            </button>
          </div>

          <TimetableManager
            subjects={subjects}
            onSessionStarted={(sid) => {
              void fetchInitialData();
              setSelectedSessionId(sid);
            }}
          />
        </>
      )}

      {/* Active Sessions Switcher */}
      {activeSessions.length > 0 && !presentationMode && (
        <div className="flex flex-wrap gap-2">
          {activeSessions.map((s) => (
            <button
              key={s.id}
              onClick={() => setSelectedSessionId(s.id)}
              className={`px-4 py-2 rounded-xl text-xs font-medium transition flex items-center space-x-2 ${
                selectedSessionId === s.id
                  ? 'bg-indigo-600 text-white shadow-glass-glow'
                  : 'glass-panel-subtle text-slate-300 hover:bg-white/10'
              }`}
            >
              <span className={`w-2 h-2 rounded-full ${s.is_paused ? 'bg-amber-400' : 'bg-emerald-400 animate-pulse'}`} />
              <span>
                {s.subject_code} ({s.classroom || 'Room'}) • {s.present_count}/{s.enrolled_count}
              </span>
            </button>
          ))}
        </div>
      )}

      {/* Live QR + Attendance Monitor */}
      {sessionDetail ? (
        <div className={`glass-panel p-8 rounded-3xl ${presentationMode ? 'border-indigo-500/40 shadow-glass-glow' : ''}`}>
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 pb-4 mb-6">
            <div>
              <div className="flex items-center space-x-2">
                <QrCode className="w-5 h-5 text-cyan-400" />
                <h2 className="text-lg font-bold text-white">
                  {sessionDetail.subject_code}: {sessionDetail.subject_name}
                </h2>
                <span
                  className={`text-[10px] px-2 py-0.5 rounded-full font-bold uppercase ${
                    sessionDetail.is_paused
                      ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                      : sessionDetail.is_active
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                      : 'bg-slate-700 text-slate-300'
                  }`}
                >
                  {sessionDetail.status}
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-1">
                {sessionDetail.classroom || 'Classroom'} • Instructor: {sessionDetail.teacher_name} • Mode:{' '}
                {sessionDetail.mode}
              </p>
            </div>

            <div className="flex items-center space-x-2">
              <button
                onClick={() => setPresentationMode((v) => !v)}
                className="px-3 py-1.5 rounded-lg glass-panel-subtle hover:bg-white/10 text-xs text-slate-200 flex items-center space-x-1.5"
              >
                {presentationMode ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
                <span>{presentationMode ? 'Exit Projection Mode' : 'Projection Mode'}</span>
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-start">
            {/* Dynamic QR Card */}
            <div className="p-6 rounded-2xl glass-card-interactive flex flex-col items-center space-y-4 text-center">
              {qrData && !sessionDetail.is_paused && sessionDetail.is_active ? (
                <div className="p-4 rounded-2xl bg-white shadow-glass-glow select-none">
                  <img
                    src={qrData.qr_image_data_url}
                    alt="Dynamic Signed Attendance QR"
                    className="w-60 h-60 object-contain pointer-events-none"
                    draggable={false}
                  />
                </div>
              ) : (
                <div className="w-64 h-64 rounded-2xl bg-slate-900/90 border border-white/10 flex flex-col items-center justify-center p-4 space-y-2">
                  <Pause className="w-10 h-10 text-amber-400" />
                  <span className="text-xs text-slate-300 font-medium">
                    {sessionDetail.is_paused ? 'Session Paused' : 'Session Closed'}
                  </span>
                </div>
              )}

              <div className="flex flex-wrap items-center justify-center gap-3 text-xs">
                <div className="px-3 py-1.5 rounded-lg bg-indigo-950/50 border border-indigo-500/30 text-indigo-300 font-mono flex items-center space-x-1.5">
                  <Clock className="w-3.5 h-3.5" />
                  <span>QR rotates in: {qrCountdown}s</span>
                </div>
                <div className="px-3 py-1.5 rounded-lg bg-cyan-950/50 border border-cyan-500/30 text-cyan-300 font-mono flex items-center space-x-1.5">
                  <Clock className="w-3.5 h-3.5" />
                  <span>Window left: {sessionCountdown}</span>
                </div>
              </div>

              {!presentationMode && (
                <>
                  <div className="flex flex-wrap justify-center gap-2 pt-2">
                    {sessionDetail.is_paused ? (
                      <button
                        onClick={() => handleSessionAction('start')}
                        className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-xs font-semibold text-white flex items-center space-x-1"
                      >
                        <Play className="w-3.5 h-3.5" />
                        <span>Resume</span>
                      </button>
                    ) : (
                      <button
                        onClick={() => handleSessionAction('pause')}
                        className="px-3 py-1.5 rounded-lg bg-amber-600/80 hover:bg-amber-600 text-xs font-semibold text-white flex items-center space-x-1"
                      >
                        <Pause className="w-3.5 h-3.5" />
                        <span>Pause</span>
                      </button>
                    )}
                    <button
                      onClick={() => handleSessionAction('extend', 3)}
                      className="px-3 py-1.5 rounded-lg glass-panel-subtle hover:bg-white/10 text-xs font-semibold text-cyan-300 flex items-center space-x-1"
                    >
                      <PlusCircle className="w-3.5 h-3.5" />
                      <span>+3 min</span>
                    </button>
                    <button
                      onClick={() => handleSessionAction('close')}
                      className="px-3 py-1.5 rounded-lg bg-red-600/80 hover:bg-red-600 text-xs font-semibold text-white flex items-center space-x-1"
                    >
                      <XCircle className="w-3.5 h-3.5" />
                      <span>Close</span>
                    </button>
                    {qrData && (
                      <button
                        onClick={copyQrTokenForTest}
                        className="px-3 py-1.5 rounded-lg glass-panel-subtle hover:bg-white/10 text-xs text-slate-300 flex items-center space-x-1"
                        title="Dev test helper: copy signed QR payload"
                      >
                        {copiedToken ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                        <span>{copiedToken ? 'Copied' : 'Copy Token (Dev)'}</span>
                      </button>
                    )}
                  </div>
                  <p className="text-[11px] text-slate-400 max-w-sm">
                    Projection mode disables copy actions and enlarges the QR for classroom projectors. Short-lived HMAC
                    tokens ({sessionDetail.qr_refresh_interval}s) limit photograph sharing; browser projection cannot block external device cameras.
                  </p>
                </>
              )}
            </div>

            {/* Real-Time Progress & Roster */}
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-3">
                <div className="p-4 rounded-xl glass-panel-subtle">
                  <div className="text-[11px] text-slate-400">Enrolled</div>
                  <div className="text-2xl font-extrabold text-white mt-1">{sessionDetail.enrolled_count}</div>
                </div>
                <div className="p-4 rounded-xl glass-panel-subtle">
                  <div className="text-[11px] text-emerald-400">Verified</div>
                  <div className="text-2xl font-extrabold text-emerald-400 mt-1">{sessionDetail.present_count}</div>
                </div>
                <div className="p-4 rounded-xl glass-panel-subtle">
                  <div className="text-[11px] text-amber-400">Pending Face</div>
                  <div className="text-2xl font-extrabold text-amber-400 mt-1">{sessionDetail.pending_count}</div>
                </div>
              </div>

              <div className="p-4 rounded-2xl glass-panel-subtle space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-semibold text-white flex items-center space-x-2">
                    <Users className="w-4 h-4 text-indigo-400" />
                    <span>Live Student Roster</span>
                  </h3>
                  <span className="text-[10px] text-emerald-400 font-mono">WebSocket Synced</span>
                </div>

                {sessionDetail.students.length === 0 ? (
                  <p className="text-xs text-slate-400 py-4 text-center">No enrolled students found for this subject.</p>
                ) : (
                  <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                    {sessionDetail.students.map((stu) => (
                      <div
                        key={stu.student_id}
                        className="p-3 rounded-xl bg-white/[0.03] border border-white/5 flex items-center justify-between text-xs"
                      >
                        <div>
                          <div className="font-semibold text-slate-100">{stu.full_name}</div>
                          <div className="text-[10px] text-slate-400 font-mono">{stu.roll_number}</div>
                        </div>
                        <span
                          className={`px-2 py-0.5 rounded-md text-[10px] font-bold ${
                            stu.status === 'PRESENT' || stu.status === 'MANUAL_OVERRIDE'
                              ? 'bg-emerald-500/20 text-emerald-300'
                              : stu.status === 'PENDING_VERIFICATION'
                              ? 'bg-amber-500/20 text-amber-300'
                              : 'bg-slate-800 text-slate-400'
                          }`}
                        >
                          {stu.status === 'PENDING_VERIFICATION' ? 'QR SCANNED • FACE PENDING' : stu.status}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="glass-panel p-10 rounded-2xl text-center space-y-2">
          <QrCode className="w-10 h-10 text-slate-500 mx-auto" />
          <div className="text-sm font-semibold text-slate-200">No Active Attendance Sessions</div>
          <p className="text-xs text-slate-400">
            Select a subject and duration above to start a real-time dynamic QR attendance session.
          </p>
        </div>
      )}
    </div>
  );
}
