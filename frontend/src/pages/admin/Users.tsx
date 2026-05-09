import { Fragment, useEffect, useState } from 'react';
import { Plus, Trash2, ChevronDown, ChevronRight, Key, UserPlus, UserMinus, UserCheck, Mail, Copy, X, Grid3x3 } from 'lucide-react';
import { api, type UserInfo, type BucketSummary, type InvitationOut } from '../../api';
import { useToast } from '../../components/Toast';
import Badge from '../../components/Badge';
import Modal from '../../components/Modal';
import AccessMatrixEditor from '../../components/AccessMatrixEditor';

type Tab = 'users' | 'invitations';

const ROLE_OPTIONS: Array<{ value: string; label: string; hint: string }> = [
  { value: 'admin', label: 'Admin', hint: 'Full system access — can manage every organization.' },
  { value: 'org_admin', label: 'Org admin', hint: 'Full access to a single organization (formerly: Manager).' },
  { value: 'user', label: 'User', hint: 'Default role — read/write within bucket permissions.' },
  { value: 'viewer', label: 'Viewer', hint: 'Read-only access; cannot edit or delete.' },
];

export default function UsersPage() {
  const { show } = useToast();
  const [tab, setTab] = useState<Tab>('users');
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [buckets, setBuckets] = useState<BucketSummary[]>([]);
  const [invitations, setInvitations] = useState<InvitationOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [editUser, setEditUser] = useState<UserInfo | null>(null);
  const [role, setRole] = useState('');
  const [active, setActive] = useState(true);

  // Create user modal
  const [createOpen, setCreateOpen] = useState(false);
  const [newEmail, setNewEmail] = useState('');
  const [newName, setNewName] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newRole, setNewRole] = useState('user');

  // Reset password modal
  const [resetUser, setResetUser] = useState<UserInfo | null>(null);
  const [resetPassword, setResetPassword] = useState('');

  // Permissions matrix modal
  const [matrixUser, setMatrixUser] = useState<UserInfo | null>(null);

  // Invite modal
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteName, setInviteName] = useState('');
  const [inviteRole, setInviteRole] = useState('user');
  const [inviteExpiry, setInviteExpiry] = useState(7);
  const [latestInvite, setLatestInvite] = useState<InvitationOut | null>(null);

  // Permissions inline panel
  const [expandedUser, setExpandedUser] = useState<string | null>(null);
  const [userPerms, setUserPerms] = useState<{ bucketId: string; bucketName: string; permId: string; permission: string }[]>([]);
  const [showAddPerm, setShowAddPerm] = useState(false);
  const [permBucket, setPermBucket] = useState('');
  const [permLevel, setPermLevel] = useState('view');

  const load = () => {
    Promise.all([api.getUsers(), api.getBuckets(), api.adminListInvitations().catch(() => [] as InvitationOut[])])
      .then(([us, bs, invs]) => { setUsers(us); setBuckets(bs); setInvitations(invs); })
      .catch(console.error)
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const createInvite = async () => {
    if (!inviteEmail.trim()) {
      show('Email is required for invitations', 'error');
      return;
    }
    try {
      const inv = await api.adminCreateInvitation({
        invited_email: inviteEmail.trim(),
        full_name_hint: inviteName.trim() || undefined,
        role: inviteRole,
        expires_in_days: inviteExpiry,
      });
      setLatestInvite(inv);
      setInviteEmail('');
      setInviteName('');
      load();
    } catch (e) {
      show(String(e), 'error');
    }
  };

  const revokeInvite = async (id: string) => {
    if (!confirm('Revoke this invitation? The link will stop working immediately.')) return;
    try {
      await api.adminRevokeInvitation(id);
      show('Invitation revoked', 'success');
      load();
    } catch (e) {
      show(String(e), 'error');
    }
  };

  const copyInviteUrl = (inv: InvitationOut) => {
    const url = `${window.location.origin}${inv.invite_url}`;
    navigator.clipboard.writeText(url).then(
      () => show('Invitation link copied to clipboard', 'success'),
      () => show('Could not copy — please copy the URL manually', 'error'),
    );
  };

  const save = async () => {
    if (!editUser) return;
    try {
      await api.updateUser(editUser.id, { role, is_active: active });
      setEditUser(null);
      load();
      show('User updated', 'success');
    } catch (e) {
      show(String(e), 'error');
    }
  };

  const createUser = async () => {
    if (!newEmail || !newName || !newPassword) {
      show('All fields are required', 'error');
      return;
    }
    try {
      await api.adminCreateUser({
        email: newEmail.trim(),
        password: newPassword,
        full_name: newName.trim(),
        role: newRole,
      });
      show(`User ${newEmail} created`, 'success');
      setCreateOpen(false);
      setNewEmail('');
      setNewName('');
      setNewPassword('');
      setNewRole('user');
      load();
    } catch (e) {
      show(String(e), 'error');
    }
  };

  const doResetPassword = async () => {
    if (!resetUser || !resetPassword) return;
    try {
      await api.adminResetPassword(resetUser.id, resetPassword);
      show(`Password reset for ${resetUser.email}`, 'success');
      setResetUser(null);
      setResetPassword('');
    } catch (e) {
      show(String(e), 'error');
    }
  };

  const toggleActive = async (u: UserInfo) => {
    try {
      if (u.is_active === false) {
        await api.updateUser(u.id, { is_active: true });
        show(`Reactivated ${u.email}`, 'success');
      } else {
        if (!confirm(`Deactivate ${u.email}?\nThe account will be unable to log in.`)) return;
        await api.adminDeactivateUser(u.id);
        show(`Deactivated ${u.email}`, 'success');
      }
      load();
    } catch (e) {
      show(String(e), 'error');
    }
  };

  const toggleExpand = async (userId: string) => {
    if (expandedUser === userId) {
      setExpandedUser(null);
      return;
    }
    setExpandedUser(userId);
    await loadUserPerms(userId);
  };

  const loadUserPerms = async (userId: string) => {
    const perms: { bucketId: string; bucketName: string; permId: string; permission: string }[] = [];
    for (const b of buckets) {
      try {
        const bp = await api.getBucketPermissions(b.id);
        for (const p of bp) {
          if (p.user_id === userId) {
            perms.push({ bucketId: b.id, bucketName: b.name, permId: p.id, permission: p.permission });
          }
        }
      } catch {
        // skip if no access
      }
    }
    setUserPerms(perms);
  };

  const addPerm = async () => {
    if (!expandedUser || !permBucket) return;
    await api.createBucketPermission(permBucket, expandedUser, permLevel);
    setShowAddPerm(false);
    setPermBucket('');
    setPermLevel('view');
    await loadUserPerms(expandedUser);
  };

  const removePerm = async (bucketId: string, permId: string) => {
    await api.deleteBucketPermission(bucketId, permId);
    if (expandedUser) await loadUserPerms(expandedUser);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Users</h1>
          <p className="text-sm text-gray-500 mt-1">Manage organization users, roles, invitations, and bucket permissions</p>
        </div>
        {tab === 'users' ? (
          <button
            onClick={() => setCreateOpen(true)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 transition-colors"
          >
            <UserPlus size={16} /> Create user
          </button>
        ) : (
          <button
            onClick={() => { setInviteOpen(true); setLatestInvite(null); }}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 transition-colors"
          >
            <Mail size={16} /> Invite user
          </button>
        )}
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-gray-800">
        {[
          { id: 'users' as Tab, label: 'Users', count: users.length },
          { id: 'invitations' as Tab, label: 'Invitations', count: invitations.filter(i => !i.redeemed_at).length },
        ].map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              tab === t.id
                ? 'text-white border-blue-500'
                : 'text-gray-500 border-transparent hover:text-gray-300'
            }`}
          >
            {t.label} <span className="ml-1.5 text-xs text-gray-600">({t.count})</span>
          </button>
        ))}
      </div>

      {tab === 'users' && (
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wider">
              <th className="w-8"></th>
              <th className="text-left px-4 py-3">Name</th>
              <th className="text-left px-4 py-3">Email</th>
              <th className="text-left px-4 py-3">Role</th>
              <th className="text-left px-4 py-3">Auth</th>
              <th className="text-left px-4 py-3">Status</th>
              <th className="text-left px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-600">Loading...</td></tr>
            ) : users.map(u => (
              <Fragment key={u.id}>
                <tr className="border-b border-gray-800/50 hover:bg-gray-800/30">
                  <td className="pl-3">
                    <button onClick={() => toggleExpand(u.id)} className="text-gray-500 hover:text-gray-300 p-1">
                      {expandedUser === u.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </button>
                  </td>
                  <td className="px-4 py-3 text-white font-medium">{u.full_name}</td>
                  <td className="px-4 py-3 text-gray-400">{u.email}</td>
                  <td className="px-4 py-3"><Badge value={u.role} /></td>
                  <td className="px-4 py-3">
                    <span className="text-xs text-gray-400">{u.auth_provider || 'local'}</span>
                    {u.email_verified === false && (
                      <span className="ml-1.5 text-xs text-amber-400" title="Email not verified">unverified</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs ${u.is_active !== false ? 'text-green-400' : 'text-red-400'}`}>
                      {u.is_active !== false ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <button
                        onClick={() => { setEditUser(u); setRole(u.role); setActive(u.is_active !== false); }}
                        className="text-xs text-blue-400 hover:underline"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => setMatrixUser(u)}
                        className="text-xs text-purple-400 hover:underline flex items-center gap-1"
                        title="Edit cross-org permissions matrix"
                      >
                        <Grid3x3 size={12} /> Permissions
                      </button>
                      <button
                        onClick={() => { setResetUser(u); setResetPassword(''); }}
                        className="text-xs text-amber-400 hover:underline flex items-center gap-1"
                        title="Reset password"
                      >
                        <Key size={12} /> Reset password
                      </button>
                      <button
                        onClick={() => toggleActive(u)}
                        className={`text-xs flex items-center gap-1 ${u.is_active === false ? 'text-green-400 hover:underline' : 'text-red-400 hover:underline'}`}
                        title={u.is_active === false ? 'Reactivate user' : 'Deactivate user'}
                      >
                        {u.is_active === false ? <><UserCheck size={12} /> Reactivate</> : <><UserMinus size={12} /> Deactivate</>}
                      </button>
                    </div>
                  </td>
                </tr>
                {expandedUser === u.id && (
                  <tr key={`${u.id}-perms`} className="bg-gray-800/20">
                    <td colSpan={7} className="px-6 py-4">
                      <div className="flex items-center justify-between mb-3">
                        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Bucket Permissions</h4>
                        <button onClick={() => setShowAddPerm(true)} className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"><Plus size={12} /> Add</button>
                      </div>
                      {userPerms.length === 0 ? (
                        <p className="text-sm text-gray-600">No bucket permissions (admin and org_admin always have full access)</p>
                      ) : (
                        <div className="space-y-1.5">
                          {userPerms.map(p => (
                            <div key={p.permId} className="flex items-center justify-between bg-gray-800/50 rounded-lg px-3 py-2">
                              <div className="text-sm">
                                <span className="text-gray-300">{p.bucketName}</span>
                                <span className="ml-2 text-xs text-gray-500">{p.permission}</span>
                              </div>
                              <button onClick={() => removePerm(p.bucketId, p.permId)} className="text-gray-500 hover:text-red-400"><Trash2 size={13} /></button>
                            </div>
                          ))}
                        </div>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      )}

      {tab === 'invitations' && (
        <div className="space-y-4">
          {invitations.length === 0 ? (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 text-center">
              <Mail size={32} className="mx-auto text-gray-600 mb-3" />
              <p className="text-sm text-gray-400">No invitations yet.</p>
              <p className="text-xs text-gray-600 mt-1">
                Invite a user by email to onboard them with prebound role and bucket permissions.
              </p>
            </div>
          ) : (
            <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wider">
                    <th className="text-left px-4 py-3">Email</th>
                    <th className="text-left px-4 py-3">Org</th>
                    <th className="text-left px-4 py-3">Role</th>
                    <th className="text-left px-4 py-3">Status</th>
                    <th className="text-left px-4 py-3">Expires</th>
                    <th className="text-left px-4 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {invitations.map(inv => {
                    const expired = !inv.redeemed_at && new Date(inv.expires_at) < new Date();
                    const status = inv.redeemed_at ? 'redeemed' : expired ? 'expired' : 'pending';
                    return (
                      <tr key={inv.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                        <td className="px-4 py-3 text-white">{inv.invited_email || <span className="text-gray-600">—</span>}</td>
                        <td className="px-4 py-3 text-gray-400">{inv.organization_name}</td>
                        <td className="px-4 py-3"><Badge value={inv.role} /></td>
                        <td className="px-4 py-3">
                          <span className={`text-xs ${
                            status === 'pending' ? 'text-amber-400'
                            : status === 'redeemed' ? 'text-green-400'
                            : 'text-gray-500'
                          }`}>
                            {status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-500">
                          {new Date(inv.expires_at).toLocaleDateString()}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-3">
                            {!inv.redeemed_at && !expired && (
                              <>
                                <button
                                  onClick={() => copyInviteUrl(inv)}
                                  className="text-xs text-blue-400 hover:underline flex items-center gap-1"
                                  title="Copy invite link"
                                >
                                  <Copy size={12} /> Copy link
                                </button>
                                <button
                                  onClick={() => revokeInvite(inv.id)}
                                  className="text-xs text-red-400 hover:underline flex items-center gap-1"
                                  title="Revoke invitation"
                                >
                                  <X size={12} /> Revoke
                                </button>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Edit user modal */}
      <Modal open={!!editUser} onClose={() => setEditUser(null)} title={`Edit: ${editUser?.full_name}`}>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Role</label>
            <select value={role} onChange={e => setRole(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              {ROLE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <p className="mt-1 text-xs text-gray-500">{ROLE_OPTIONS.find(o => o.value === role)?.hint}</p>
          </div>
          <div className="flex items-center gap-3">
            <label className="text-sm text-gray-400">Active</label>
            <input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)} className="rounded" />
          </div>
          <button onClick={save} className="w-full py-2.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 transition-colors">Save Changes</button>
        </div>
      </Modal>

      {/* Create user modal */}
      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="Create user">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Full name</label>
            <input
              type="text"
              value={newName}
              onChange={e => setNewName(e.target.value)}
              placeholder="Jane Smith"
              className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Email</label>
            <input
              type="email"
              value={newEmail}
              onChange={e => setNewEmail(e.target.value)}
              placeholder="jane@example.com"
              autoComplete="off"
              className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Initial password</label>
            <input
              type="password"
              value={newPassword}
              onChange={e => setNewPassword(e.target.value)}
              placeholder="Min 8 chars, 1 uppercase, 1 digit"
              autoComplete="new-password"
              className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <p className="mt-1 text-xs text-gray-500">The user can change this from their profile after first login.</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Role</label>
            <select value={newRole} onChange={e => setNewRole(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              {ROLE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <p className="mt-1 text-xs text-gray-500">{ROLE_OPTIONS.find(o => o.value === newRole)?.hint}</p>
          </div>
          <button onClick={createUser} className="w-full py-2.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 transition-colors">Create user</button>
        </div>
      </Modal>

      {/* Reset password modal */}
      <Modal open={!!resetUser} onClose={() => setResetUser(null)} title={`Reset password: ${resetUser?.email}`}>
        <div className="space-y-4">
          <p className="text-sm text-gray-400">
            Set a new password for this user. The account is also unlocked if it was locked due to failed logins.
          </p>
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">New password</label>
            <input
              type="password"
              value={resetPassword}
              onChange={e => setResetPassword(e.target.value)}
              placeholder="Min 8 chars, 1 uppercase, 1 digit"
              autoComplete="new-password"
              className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-amber-500"
            />
          </div>
          <button onClick={doResetPassword} className="w-full py-2.5 rounded-lg bg-amber-600 text-white text-sm font-medium hover:bg-amber-500 transition-colors">Reset password</button>
        </div>
      </Modal>

      {/* Cross-org permissions matrix editor */}
      {matrixUser && (
        <AccessMatrixEditor
          userId={matrixUser.id}
          userLabel={`${matrixUser.full_name} <${matrixUser.email}>`}
          onClose={() => setMatrixUser(null)}
          onSaved={load}
          showToast={show}
        />
      )}

      {/* Invite user modal */}
      <Modal
        open={inviteOpen}
        onClose={() => { setInviteOpen(false); setLatestInvite(null); }}
        title={latestInvite ? 'Invitation ready' : 'Invite a user'}
      >
        {latestInvite ? (
          <div className="space-y-4">
            <p className="text-sm text-gray-300">
              Share this link with <span className="text-white font-medium">{latestInvite.invited_email}</span>.
              They have until <span className="text-white">{new Date(latestInvite.expires_at).toLocaleString()}</span> to redeem it.
            </p>
            <div className="bg-gray-800 border border-gray-700 rounded-lg p-3 font-mono text-xs text-gray-300 break-all">
              {window.location.origin}{latestInvite.invite_url}
            </div>
            <button
              onClick={() => copyInviteUrl(latestInvite)}
              className="w-full py-2.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 transition-colors flex items-center justify-center gap-2"
            >
              <Copy size={14} /> Copy link
            </button>
            <button
              onClick={() => { setInviteOpen(false); setLatestInvite(null); }}
              className="w-full py-2 rounded-lg bg-gray-800 text-gray-300 text-sm font-medium hover:bg-gray-700 transition-colors"
            >
              Done
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1.5">Email</label>
              <input
                type="email"
                value={inviteEmail}
                onChange={e => setInviteEmail(e.target.value)}
                placeholder="alice@example.com"
                autoComplete="off"
                className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1.5">Suggested name (optional)</label>
              <input
                type="text"
                value={inviteName}
                onChange={e => setInviteName(e.target.value)}
                placeholder="Alice Smith"
                className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <p className="mt-1 text-xs text-gray-500">Pre-fills the recipient's name field. They can change it.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1.5">Role</label>
              <select value={inviteRole} onChange={e => setInviteRole(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                {ROLE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <p className="mt-1 text-xs text-gray-500">{ROLE_OPTIONS.find(o => o.value === inviteRole)?.hint}</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1.5">Expires in</label>
              <select value={inviteExpiry} onChange={e => setInviteExpiry(parseInt(e.target.value))} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value={1}>1 day</option>
                <option value={7}>7 days</option>
                <option value={30}>30 days</option>
                <option value={90}>90 days</option>
              </select>
            </div>
            <button onClick={createInvite} className="w-full py-2.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 transition-colors">
              Generate invitation link
            </button>
          </div>
        )}
      </Modal>

      <Modal open={showAddPerm} onClose={() => setShowAddPerm(false)} title="Add Bucket Permission">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Bucket</label>
            <select value={permBucket} onChange={e => setPermBucket(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="">Select bucket...</option>
              {buckets.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Permission</label>
            <select value={permLevel} onChange={e => setPermLevel(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="view">View</option>
              <option value="edit">Edit</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <button onClick={addPerm} className="w-full py-2.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 transition-colors">Add Permission</button>
        </div>
      </Modal>
    </div>
  );
}
