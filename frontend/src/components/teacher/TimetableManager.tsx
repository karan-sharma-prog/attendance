import { useState, useEffect, useCallback, ChangeEvent, FormEvent } from 'react';
import {
  Calendar,
  Upload,
  PlusCircle,
  Trash2,
  Play,
  Download,
  Users,
  CheckCircle2,
  AlertCircle,
  Loader2,
} from 'lucide-react';
import { api, SubjectItem, TimetableResponse } from '../../services/api';

const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

const SAMPLE_CSE_CSV = `day_of_week,start_time,end_time,subject_code,room_number,auto_open_offset_minutes,auto_close_offset_minutes,qr_refresh_interval
Monday,09:00,10:00,CS-401,CSE Hall 302,3,5,8
Tuesday,10:00,11:00,CS-403,AI Robotics Lab,3,5,8
Wednesday,11:00,12:00,CS-405,CSE Seminar 201,3,5,8
Thursday,10:00,11:00,CS-407,CSE Hall 302,3,5,8
Friday,14:00,15:00,CS-401,CSE Hall 302,3,5,8`;

interface TimetableManagerProps {
  subjects: SubjectItem[];
  onSessionStarted: (sessionId: string) => void;
}

export function TimetableManager({ subjects, onSessionStarted }: TimetableManagerProps) {
  const [scope, setScope] = useState<'mine' | 'department'>('mine');
  const [timetables, setTimetables] = useState<TimetableResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [replaceExisting, setReplaceExisting] = useState(false);
  const [autoMatchCse, setAutoMatchCse] = useState(true);
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Manual single-slot form
  const [subjectCode, setSubjectCode] = useState('CS-401');
  const [dayOfWeek, setDayOfWeek] = useState<number>(0);
  const [startTime, setStartTime] = useState('09:00');
  const [endTime, setEndTime] = useState('10:00');
  const [roomNumber, setRoomNumber] = useState('CSE Hall 302');

  const loadTimetables = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<TimetableResponse[]>(`/sessions/timetables?scope=${scope}`);
      setTimetables(res.data);
    } catch {
      setTimetables([]);
    } finally {
      setLoading(false);
    }
  }, [scope]);

  useEffect(() => {
    void loadTimetables();
  }, [loadTimetables]);

  const handleFileUpload = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setFeedback(null);
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('replace_existing', String(replaceExisting));
      form.append('auto_enroll_department_students', String(autoMatchCse));
      const res = await api.post('/sessions/timetables/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      const errNote = res.data.errors?.length ? ` Warnings: ${res.data.errors.join(' | ')}` : '';
      setFeedback({
        type: res.data.created_count > 0 ? 'success' : 'error',
        text: `Uploaded ${res.data.created_count} CSE timetable slot(s). Matched ${res.data.matched_students_enrolled} new student enrollment(s).${errNote}`,
      });
      await loadTimetables();
    } catch (err: any) {
      setFeedback({ type: 'error', text: err?.response?.data?.detail || 'CSV upload failed.' });
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  const handleUploadSampleCse = async () => {
    setUploading(true);
    setFeedback(null);
    try {
      const res = await api.post('/sessions/timetables/upload-csv', {
        csv_content: SAMPLE_CSE_CSV,
        replace_existing: replaceExisting,
        auto_enroll_department_students: autoMatchCse,
      });
      const errNote = res.data.errors?.length ? ` (${res.data.errors.join(' | ')})` : '';
      setFeedback({
        type: res.data.created_count > 0 ? 'success' : 'error',
        text: `Published ${res.data.created_count} CSE timetable slot(s) and synced with student schedules.${errNote}`,
      });
      await loadTimetables();
    } catch (err: any) {
      setFeedback({ type: 'error', text: err?.response?.data?.detail || 'Failed to publish sample CSE schedule.' });
    } finally {
      setUploading(false);
    }
  };

  const handleDownloadTemplate = () => {
    const blob = new Blob([SAMPLE_CSE_CSV], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'smartpresence_cse_timetable_template.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleAddSingleSlot = async (e: FormEvent) => {
    e.preventDefault();
    setUploading(true);
    setFeedback(null);
    try {
      await api.post('/sessions/timetables', {
        subject_code: subjectCode,
        day_of_week: dayOfWeek,
        start_time: startTime,
        end_time: endTime,
        room_number: roomNumber,
      });
      setFeedback({ type: 'success', text: `Added ${subjectCode} slot and matched CSE students.` });
      await loadTimetables();
    } catch (err: any) {
      setFeedback({ type: 'error', text: err?.response?.data?.detail || 'Failed to add timetable slot.' });
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteSlot = async (id: string) => {
    setFeedback(null);
    try {
      await api.delete(`/sessions/timetables/${id}`);
      await loadTimetables();
    } catch (err: any) {
      setFeedback({ type: 'error', text: err?.response?.data?.detail || 'Could not remove slot.' });
    }
  };

  const handleStartNow = async (id: string) => {
    setFeedback(null);
    try {
      const res = await api.post(`/sessions/timetables/${id}/start-now?duration_minutes=5`);
      onSessionStarted(res.data.id);
    } catch (err: any) {
      setFeedback({ type: 'error', text: err?.response?.data?.detail || 'Could not start session from slot.' });
    }
  };

  return (
    <div className="glass-panel p-6 rounded-2xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-3">
        <div>
          <h3 className="text-base font-bold text-white flex items-center space-x-2">
            <Calendar className="w-5 h-5 text-cyan-400" />
            <span>Timetable Upload &amp; Matched CSE Class Schedule</span>
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Upload a CSV timetable or add slots. Uploaded CSE classes automatically match every CSE student&apos;s timetable.
          </p>
        </div>

        <div className="flex items-center space-x-1 bg-slate-900/70 p-1 rounded-xl border border-white/10 text-xs">
          <button
            type="button"
            onClick={() => setScope('mine')}
            className={`px-3 py-1.5 rounded-lg font-medium transition ${
              scope === 'mine' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'
            }`}
          >
            My Teacher Schedule
          </button>
          <button
            type="button"
            onClick={() => setScope('department')}
            className={`px-3 py-1.5 rounded-lg font-medium transition ${
              scope === 'department' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'
            }`}
          >
            Matched CSE Class Schedule
          </button>
        </div>
      </div>

      {feedback && (
        <div
          className={`p-3 rounded-xl text-xs flex items-start space-x-2 border ${
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

      {/* CSV Upload Controls */}
      <div className="p-4 rounded-2xl glass-panel-subtle space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <label className="btn-primary px-4 py-2 rounded-xl text-xs font-semibold text-white flex items-center space-x-2 cursor-pointer">
              {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
              <span>Upload Timetable (.CSV)</span>
              <input type="file" accept=".csv,text/csv" onChange={handleFileUpload} className="hidden" />
            </label>

            <button
              type="button"
              onClick={handleUploadSampleCse}
              disabled={uploading}
              className="btn-cyan px-4 py-2 rounded-xl text-xs font-semibold text-white"
            >
              Load Sample CSE Weekly Schedule
            </button>

            <button
              type="button"
              onClick={handleDownloadTemplate}
              className="px-3 py-2 rounded-xl glass-panel-subtle hover:bg-white/10 text-xs text-slate-300 flex items-center space-x-1.5"
            >
              <Download className="w-3.5 h-3.5" />
              <span>CSV Template</span>
            </button>
          </div>
        </div>

        <div className="flex flex-wrap gap-4 text-xs text-slate-300">
          <label className="flex items-center space-x-2 cursor-pointer">
            <input
              type="checkbox"
              checked={autoMatchCse}
              onChange={(e) => setAutoMatchCse(e.target.checked)}
              className="accent-indigo-500"
            />
            <span>Automatically match &amp; enroll all CSE students to uploaded classes</span>
          </label>
          <label className="flex items-center space-x-2 cursor-pointer">
            <input
              type="checkbox"
              checked={replaceExisting}
              onChange={(e) => setReplaceExisting(e.target.checked)}
              className="accent-indigo-500"
            />
            <span>Replace my previous timetable slots</span>
          </label>
        </div>
      </div>

      {/* Add Single Timetable Slot */}
      <form onSubmit={handleAddSingleSlot} className="grid grid-cols-2 sm:grid-cols-6 gap-2 items-end">
        <select
          value={subjectCode}
          onChange={(e) => setSubjectCode(e.target.value)}
          className="glass-input px-2.5 py-2 rounded-xl text-xs bg-slate-900"
        >
          {subjects.map((s) => (
            <option key={s.id} value={s.code}>
              {s.code}
            </option>
          ))}
        </select>
        <select
          value={dayOfWeek}
          onChange={(e) => setDayOfWeek(Number(e.target.value))}
          className="glass-input px-2.5 py-2 rounded-xl text-xs bg-slate-900"
        >
          {DAY_NAMES.map((d, i) => (
            <option key={d} value={i}>
              {d}
            </option>
          ))}
        </select>
        <input
          type="time"
          value={startTime}
          onChange={(e) => setStartTime(e.target.value)}
          className="glass-input px-2.5 py-2 rounded-xl text-xs"
        />
        <input
          type="time"
          value={endTime}
          onChange={(e) => setEndTime(e.target.value)}
          className="glass-input px-2.5 py-2 rounded-xl text-xs"
        />
        <input
          type="text"
          value={roomNumber}
          onChange={(e) => setRoomNumber(e.target.value)}
          placeholder="Room"
          className="glass-input px-2.5 py-2 rounded-xl text-xs"
        />
        <button
          type="submit"
          disabled={uploading}
          className="btn-primary py-2 px-3 rounded-xl text-xs font-semibold text-white flex items-center justify-center space-x-1"
        >
          <PlusCircle className="w-3.5 h-3.5" />
          <span>Add Slot</span>
        </button>
      </form>

      {/* Schedule Table */}
      {loading ? (
        <div className="py-6 flex justify-center">
          <Loader2 className="w-5 h-5 animate-spin text-indigo-400" />
        </div>
      ) : timetables.length === 0 ? (
        <div className="p-6 rounded-xl glass-panel-subtle text-center text-xs text-slate-400">
          No timetable slots found yet. Upload a CSV or click &quot;Load Sample CSE Weekly Schedule&quot; above.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {timetables.map((tt) => (
            <div key={tt.id} className="p-4 rounded-xl glass-panel-subtle flex items-center justify-between gap-3 text-xs">
              <div className="space-y-1">
                <div className="font-bold text-white flex items-center space-x-2">
                  <span className="text-cyan-300">{DAY_NAMES[tt.day_of_week]}</span>
                  <span>•</span>
                  <span className="font-mono">
                    {tt.start_time}–{tt.end_time}
                  </span>
                </div>
                <div className="text-slate-200 font-semibold">
                  {tt.subject_code}: {tt.subject_name}
                </div>
                <div className="text-[11px] text-slate-400 flex items-center space-x-2">
                  <span>{tt.room_number}</span>
                  <span>•</span>
                  <span>Instructor: {tt.teacher_name}</span>
                  <span>•</span>
                  <span className="text-emerald-300 inline-flex items-center space-x-1">
                    <Users className="w-3 h-3" />
                    <span>{tt.matched_student_count} {tt.department_code} matched</span>
                  </span>
                </div>
              </div>

              <div className="flex items-center space-x-1.5 shrink-0">
                <button
                  type="button"
                  onClick={() => handleStartNow(tt.id)}
                  title="Start live QR session now for this class"
                  className="p-2 rounded-lg bg-indigo-600/80 hover:bg-indigo-500 text-white"
                >
                  <Play className="w-3.5 h-3.5" />
                </button>
                {scope === 'mine' && (
                  <button
                    type="button"
                    onClick={() => handleDeleteSlot(tt.id)}
                    title="Delete slot"
                    className="p-2 rounded-lg bg-red-600/70 hover:bg-red-600 text-white"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
