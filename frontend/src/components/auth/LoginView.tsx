import { useState, FormEvent } from 'react';
import { ShieldCheck, Lock, Mail, AlertCircle, Loader2, Sparkles } from 'lucide-react';
import { api, setAuthTokens, AuthUser } from '../../services/api';

interface LoginViewProps {
  onLoginSuccess: (user: AuthUser) => void;
  pendingQrDetected?: boolean;
}

export function LoginView({ onLoginSuccess, pendingQrDetected = false }: LoginViewProps) {
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await api.post('/auth/login', { identifier, password });
      setAuthTokens(res.data.access_token, res.data.refresh_token);
      onLoginSuccess({
        user_id: res.data.user_id,
        email: res.data.email,
        full_name: res.data.full_name,
        role: res.data.role,
        student_id: res.data.student_id,
        teacher_id: res.data.teacher_id,
      });
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Authentication failed. Check your credentials and backend connectivity.');
    } finally {
      setLoading(false);
    }
  };

  const fillSeededAccount = (email: string, pass: string) => {
    setIdentifier(email);
    setPassword(pass);
    setError(null);
  };

  return (
    <div className="min-h-screen bg-[#080F1F] text-[#F8FAFC] flex items-center justify-center p-4 relative overflow-hidden">
      <div className="absolute top-[-15%] left-[-10%] w-[520px] h-[520px] bg-indigo-600/20 rounded-full blur-[130px] pointer-events-none" />
      <div className="absolute bottom-[-15%] right-[-10%] w-[520px] h-[520px] bg-cyan-500/15 rounded-full blur-[140px] pointer-events-none" />

      <div className="w-full max-w-md glass-panel rounded-3xl p-8 space-y-6 relative z-10">
        <div className="text-center space-y-2">
          <div className="w-14 h-14 mx-auto rounded-2xl bg-gradient-to-tr from-indigo-500 to-cyan-400 p-[1.5px] shadow-glass-glow">
            <div className="w-full h-full bg-[#080F1F] rounded-[14px] flex items-center justify-center">
              <ShieldCheck className="w-7 h-7 text-cyan-400" />
            </div>
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight">SmartPresence</h1>
          <p className="text-xs text-slate-400">
            AI-Integrated Attendance • Dynamic QR • Biometric Liveness
          </p>
        </div>

        {pendingQrDetected && (
          <div className="p-3 rounded-xl bg-cyan-950/60 border border-cyan-500/40 text-xs text-cyan-200">
            Attendance QR link detected! Sign in with your student account to verify your attendance immediately.
          </div>
        )}

        {error && (
          <div className="p-3 rounded-xl bg-red-950/60 border border-red-500/40 text-xs text-red-200 flex items-start space-x-2">
            <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-300">Institutional Email or Enrollment ID</label>
            <div className="relative">
              <Mail className="w-4 h-4 text-slate-400 absolute left-3.5 top-3" />
              <input
                type="text"
                required
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                placeholder="e.g. alex.rivera@smartpresence.edu or CS2024-8841"
                className="w-full glass-input pl-10 pr-4 py-2.5 rounded-xl text-xs"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-300">Password</label>
            <div className="relative">
              <Lock className="w-4 h-4 text-slate-400 absolute left-3.5 top-3" />
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                className="w-full glass-input pl-10 pr-4 py-2.5 rounded-xl text-xs"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 rounded-xl btn-primary text-xs font-semibold text-white flex items-center justify-center space-x-2 disabled:opacity-60"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            <span>{loading ? 'Authenticating with Neon DB...' : 'Sign In'}</span>
          </button>
        </form>

        {/* Development convenience quick-fill (still authenticates via real Argon2id backend API) */}
        <div className="pt-4 border-t border-white/10 space-y-2">
          <div className="text-[11px] text-slate-400 text-center">
            Seeded Neon Test Accounts (Verified via Argon2id API)
          </div>
          <div className="grid grid-cols-3 gap-2">
            <button
              type="button"
              onClick={() => fillSeededAccount('alex.rivera@smartpresence.edu', 'StudentPass@2026')}
              className="py-1.5 px-2 rounded-lg glass-panel-subtle hover:bg-white/10 text-[11px] text-cyan-300 font-medium transition"
            >
              Student
            </button>
            <button
              type="button"
              onClick={() => fillSeededAccount('faculty.vance@smartpresence.edu', 'FacultyPass@2026')}
              className="py-1.5 px-2 rounded-lg glass-panel-subtle hover:bg-white/10 text-[11px] text-indigo-300 font-medium transition"
            >
              Teacher
            </button>
            <button
              type="button"
              onClick={() => fillSeededAccount('admin@smartpresence.edu', 'AdminPass@2026')}
              className="py-1.5 px-2 rounded-lg glass-panel-subtle hover:bg-white/10 text-[11px] text-purple-300 font-medium transition"
            >
              Admin
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
