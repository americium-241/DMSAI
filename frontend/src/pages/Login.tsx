import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth';
import { api, type AuthProviders } from '../api';
import { FileText, Mail, ShieldCheck } from 'lucide-react';

export default function LoginPage() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [orgName, setOrgName] = useState('');
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [loading, setLoading] = useState(false);
  const [verificationSent, setVerificationSent] = useState(false);
  const [providers, setProviders] = useState<AuthProviders | null>(null);

  useEffect(() => {
    api.getAuthProviders().then(setProviders).catch(() => {});
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setInfo('');
    setLoading(true);
    try {
      if (isRegister) {
        const result = await register(email, password, fullName, orgName || undefined);
        if (result.verification_required) {
          setVerificationSent(true);
          setInfo(result.message || 'Please check your email to verify your account.');
          return;
        }
      } else {
        await login(email, password);
      }
      navigate('/');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Authentication failed';
      try {
        const parsed = JSON.parse(msg);
        setError(parsed.detail || msg);
      } catch {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleResendVerification = async () => {
    if (!email) return;
    setLoading(true);
    try {
      const resp = await api.resendVerification(email);
      setInfo(resp.message);
    } catch {
      setInfo('Verification email sent if the address exists.');
    } finally {
      setLoading(false);
    }
  };

  const registrationAllowed = providers?.registration_open !== false;

  if (verificationSent) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
        <div className="w-full max-w-md">
          <div className="text-center mb-8">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-green-600/20 mb-4">
              <Mail size={28} className="text-green-400" />
            </div>
            <h1 className="text-2xl font-bold text-white">Check Your Email</h1>
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 text-center">
            <p className="text-gray-300 mb-4">{info}</p>
            <p className="text-sm text-gray-500 mb-6">
              A verification link has been sent to <span className="text-white font-medium">{email}</span>.
              Click the link to activate your account.
            </p>

            <button
              onClick={handleResendVerification}
              disabled={loading}
              className="w-full py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-gray-300 text-sm font-medium hover:bg-gray-700 disabled:opacity-50 transition-colors mb-3"
            >
              {loading ? 'Sending...' : 'Resend Verification Email'}
            </button>

            <button
              onClick={() => { setVerificationSent(false); setIsRegister(false); setError(''); setInfo(''); }}
              className="text-sm text-blue-400 hover:text-blue-300 transition-colors"
            >
              Back to Sign In
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-blue-600/20 mb-4">
            <FileText size={28} className="text-blue-400" />
          </div>
          <h1 className="text-2xl font-bold text-white">DMSAI</h1>
          <p className="text-sm text-gray-500 mt-1">Document Management System with AI</p>
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
          <h2 className="text-lg font-semibold text-white mb-6">
            {isRegister ? 'Create Account' : 'Sign In'}
          </h2>

          {providers?.ldap && !isRegister && (
            <div className="mb-4 flex items-center gap-2 px-3 py-2 rounded-lg bg-blue-500/10 border border-blue-500/20">
              <ShieldCheck size={16} className="text-blue-400 shrink-0" />
              <span className="text-xs text-blue-300">
                LDAP authentication is enabled. Use your directory credentials to sign in.
              </span>
            </div>
          )}

          {error && (
            <div className="mb-4 px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
              {error}
            </div>
          )}

          {info && !error && (
            <div className="mb-4 px-4 py-3 rounded-lg bg-blue-500/10 border border-blue-500/30 text-blue-400 text-sm">
              {info}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {isRegister && (
              <>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1.5">Full Name</label>
                  <input
                    type="text" value={fullName} onChange={e => setFullName(e.target.value)} required
                    className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    placeholder="John Doe"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1.5">Organization Name</label>
                  <input
                    type="text" value={orgName} onChange={e => setOrgName(e.target.value)}
                    className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    placeholder="ACME Corp"
                  />
                </div>
              </>
            )}

            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1.5">Email</label>
              <input
                type="email" value={email} onChange={e => setEmail(e.target.value)} required
                className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="user@example.com"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1.5">Password</label>
              <input
                type="password" value={password} onChange={e => setPassword(e.target.value)} required
                className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="********"
              />
              {isRegister && (
                <p className="mt-1.5 text-xs text-gray-500">
                  Min. 8 characters, one uppercase letter, one digit.
                </p>
              )}
            </div>

            <button
              type="submit" disabled={loading}
              className="w-full py-2.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 disabled:opacity-50 transition-colors"
            >
              {loading ? 'Please wait...' : (isRegister ? 'Create Account' : 'Sign In')}
            </button>
          </form>

          {registrationAllowed && (
            <div className="mt-4 text-center">
              <button
                onClick={() => { setIsRegister(!isRegister); setError(''); setInfo(''); }}
                className="text-sm text-blue-400 hover:text-blue-300 transition-colors"
              >
                {isRegister ? 'Already have an account? Sign In' : "Don't have an account? Register"}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
