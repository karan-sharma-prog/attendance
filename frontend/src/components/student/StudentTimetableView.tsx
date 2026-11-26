import { useState, useEffect, useCallback } from 'react';
import { Calendar, Clock, QrCode, Users, Loader2 } from 'lucide-react';
import { api, SessionSummary, TimetableResponse } from '../../services/api';

const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

interface StudentTimetableViewProps {
  activeSessions: SessionSummary[];
  onScanClick: () => void;
}

export function StudentTimetableView({ activeSessions, onScanClick }: StudentTimetableViewProps) {
  const [timetables, setTimetables] = useState<TimetableResponse[]>([]);
  const [loading, setLoading] = useState(true);

  const loadSchedule = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<TimetableResponse[]>('/sessions/timetables');
      setTimetables(res.data);
    } catch {
      setTimetables([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSchedule();
  }, [loadSchedule]);

  // JS getDay(): 0=Sun..6=Sat -> Python weekday: 0=Mon..6=Sun
  const jsDay = new Date().getDay();
  const todayIdx = jsDay === 0 ? 6 : jsDay - 1;
  const activeSubjectCodes = new Set(activeSessions.map((s) => s.subject_code));
  const todaysClasses = timetables.filter((t) => t.day_of_week === todayIdx);

  return (
    <div className="glass-panel p-6 rounded-2xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold text-white flex items-center space-x-2">
            <Calendar className="w-4 h-4 text-cyan-400" />
            <span>Matched CSE Class Timetable ({DAY_NAMES[todayIdx]} &amp; Weekly)</span>
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Automatically synced with your CSE faculty instructors&apos; uploaded schedules.
          </p>
        </div>
        <button type="button" onClick={loadSchedule} className="text-xs text-cyan-300 hover:underline">
          Sync Schedule
        </button>
      </div>

      {loading ? (
        <div className="py-6 flex justify-center">
          <Loader2 className="w-5 h-5 animate-spin text-indigo-400" />
        </div>
      ) : timetables.length === 0 ? (
        <div className="p-5 rounded-xl glass-panel-subtle text-center text-xs text-slate-400">
          No timetable slots uploaded by your CSE faculty yet.
        </div>
      ) : (
        <div className="space-y-4">
          {todaysClasses.length > 0 && (
            <div className="space-y-2">
              <div className="text-[11px] font-bold uppercase tracking-wider text-cyan-300">
                Today&apos;s Classes ({DAY_NAMES[todayIdx]})
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {todaysClasses.map((tt) => {
                  const isLive = activeSubjectCodes.has(tt.subject_code);
                  return (
                    <div
                      key={`today-${tt.id}`}
                      className={`p-4 rounded-xl border flex items-center justify-between gap-3 text-xs ${
                        isLive ? 'bg-indigo-950/50 border-indigo-500/60' : 'glass-panel-subtle border-white/10'
                      }`}
                    >
                      <div className="space-y-1">
                        <div className="font-bold text-white">
                          {tt.subject_code}: {tt.subject_name}
                        </div>
                        <div className="text-[11px] text-slate-300 flex items-center space-x-2">
                          <Clock className="w-3 h-3 text-cyan-400" />
                          <span className="font-mono">
                            {tt.start_time}–{tt.end_time}
                          </span>
                          <span>•</span>
                          <span>{tt.room_number}</span>
                          <span>•</span>
                          <span>Prof: {tt.teacher_name}</span>
                        </div>
                      </div>
                      {isLive && (
                        <button
                          type="button"
                          onClick={onScanClick}
                          className="btn-primary px-3 py-1.5 rounded-lg text-[11px] font-semibold text-white flex items-center space-x-1 shrink-0"
                        >
                          <QrCode className="w-3.5 h-3.5" />
                          <span>Scan QR</span>
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <div className="space-y-2">
            <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
              Full Weekly CSE Schedule ({timetables.length} Slots)
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2.5">
              {timetables.map((tt) => (
                <div key={tt.id} className="p-3.5 rounded-xl glass-panel-subtle text-xs space-y-1">
                  <div className="flex justify-between font-bold text-slate-100">
                    <span className="text-cyan-300">{DAY_NAMES[tt.day_of_week]}</span>
                    <span className="font-mono">
                      {tt.start_time}–{tt.end_time}
                    </span>
                  </div>
                  <div className="font-semibold text-white truncate">
                    {tt.subject_code}: {tt.subject_name}
                  </div>
                  <div className="text-[11px] text-slate-400 flex items-center justify-between">
                    <span>{tt.room_number}</span>
                    <span className="inline-flex items-center space-x-1 text-indigo-300">
                      <Users className="w-3 h-3" />
                      <span>{tt.teacher_name}</span>
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
