import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Mail, Building2, Shield, AlertCircle, Loader } from 'lucide-react';
import { api, type InvitationOut } from '../api';

/**
 * Public landing page for the invitation flow.
 *
 * URL shape: ``/invite/<token>``
 *
 * 1. Look up the invitation (no auth) and display the org/role context.
 * 2. Collect a password and full name (full name is pre-filled from
 *    ``full_name_hint`` if the admin provided one).
 * 3. Call POST /api/invitations/{token}/redeem and log the user in
 *    with the returned access token.
 */
export default function InviteRedeemPage() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const [invitation, setInvitation] = useState<InvitationOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  useEffect(() => {
    if (!token) {
      setError('Missing invitation token');
      setLoading(false);
      return;
    }
    api
      .lookupInvitation(token)
      .then(inv => {
        setInvitation(inv);
        setFullName(inv.full_name_hint || '');
      })
      .catch(e => setError(typeof e === 'string' ? e : (e?.message || 'Invitation not found or expired')))
      .finally(() => setLoading(false));
  }, [token]);

  const submit = async () => {
    if (!token || !invitation) return;
    if (!fullName.trim()) {
      setError('Please enter your full name');
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords don't match");
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const resp = await api.redeemInvitation(token, password, fullName.trim());
      if (resp.access_token) {
        localStorage.setItem('dmsai_token', resp.access_token);
        localStorage.setItem('dmsai_user', JSON.stringify(resp.user));
      }
      // Hard navigate so AuthProvider rehydrates from localStorage on mount.
      window.location.href = '/';
    } catch (e: any) {
      setError(typeof e === 'string' ? e : (e?.message || 'Redemption failed'));
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-950">
        <Loader className="animate-spin text-blue-400" size={32} />
      </div>
    );
  }

  if (error && !invitation) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-950 p-6">
        <div className="max-w-md w-full bg-gray-900 border border-red-500/30 rounded-xl p-6 space-y-4">
          <div className="flex items-center gap-3 text-red-400">
            <AlertCircle size={24} />
            <h1 className="text-lg font-semibold">Invitation unavailable</h1>
          </div>
          <p className="text-sm text-gray-400">{error}</p>
          <p className="text-xs text-gray-500">
            Ask the administrator to send a new invitation, or sign in with an existing account.
          </p>
          <button
            onClick={() => navigate('/login')}
            className="w-full py-2.5 rounded-lg bg-gray-800 text-gray-300 text-sm font-medium hover:bg-gray-700 transition-colors"
          >
            Go to login
          </button>
        </div>
      </div>
    );
  }

  if (!invitation) return null;

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950 p-6">
      <div className="max-w-md w-full bg-gray-900 border border-gray-800 rounded-xl p-8 space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-white">You're invited</h1>
          <p className="text-sm text-gray-500 mt-1">Complete the form below to activate your account.</p>
        </div>

        <div className="space-y-2 bg-gray-800/40 border border-gray-800 rounded-lg p-4">
          <div className="flex items-center gap-2 text-sm">
            <Building2 size={16} className="text-blue-400" />
            <span className="text-gray-400">Organization</span>
            <span className="ml-auto text-white font-medium">{invitation.organization_name}</span>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Shield size={16} className="text-purple-400" />
            <span className="text-gray-400">Role</span>
            <span className="ml-auto text-white font-medium">{invitation.role}</span>
          </div>
          {invitation.invited_email && (
            <div className="flex items-center gap-2 text-sm">
              <Mail size={16} className="text-amber-400" />
              <span className="text-gray-400">Email</span>
              <span className="ml-auto text-white font-mono text-xs">{invitation.invited_email}</span>
            </div>
          )}
          {invitation.bucket_grants.length > 0 && (
            <div className="text-xs text-gray-500 pt-2 border-t border-gray-800">
              You will receive {invitation.bucket_grants.length} bucket permission(s) on join.
            </div>
          )}
        </div>

        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Full name</label>
            <input
              type="text"
              value={fullName}
              onChange={e => setFullName(e.target.value)}
              placeholder="Jane Smith"
              className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="Min 8 chars, 1 uppercase, 1 digit"
              autoComplete="new-password"
              className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Confirm password</label>
            <input
              type="password"
              value={confirmPassword}
              onChange={e => setConfirmPassword(e.target.value)}
              autoComplete="new-password"
              className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-sm text-red-400 flex items-center gap-2">
            <AlertCircle size={16} /> {error}
          </div>
        )}

        <button
          onClick={submit}
          disabled={submitting}
          className="w-full py-3 rounded-lg bg-blue-600 text-white font-medium hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {submitting ? 'Activating account...' : 'Accept and create account'}
        </button>
      </div>
    </div>
  );
}
