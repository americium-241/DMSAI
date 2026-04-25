import { Fragment, useEffect, useState } from 'react';
import { Plus, Trash2, ChevronDown, ChevronRight } from 'lucide-react';
import { api, type UserInfo, type BucketSummary } from '../../api';
import { useToast } from '../../components/Toast';
import Badge from '../../components/Badge';
import Modal from '../../components/Modal';

export default function UsersPage() {
  const { show } = useToast();
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [buckets, setBuckets] = useState<BucketSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [editUser, setEditUser] = useState<UserInfo | null>(null);
  const [role, setRole] = useState('');
  const [active, setActive] = useState(true);

  // Permissions
  const [expandedUser, setExpandedUser] = useState<string | null>(null);
  const [userPerms, setUserPerms] = useState<{ bucketId: string; bucketName: string; permId: string; permission: string }[]>([]);
  const [showAddPerm, setShowAddPerm] = useState(false);
  const [permBucket, setPermBucket] = useState('');
  const [permLevel, setPermLevel] = useState('view');

  const load = () => {
    Promise.all([api.getUsers(), api.getBuckets()])
      .then(([us, bs]) => { setUsers(us); setBuckets(bs); })
      .catch(console.error)
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

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
      <div>
        <h1 className="text-2xl font-bold text-white">Users</h1>
        <p className="text-sm text-gray-500 mt-1">Manage organization users, roles, and bucket permissions</p>
      </div>

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
                    <button onClick={() => { setEditUser(u); setRole(u.role); setActive(u.is_active !== false); }} className="text-xs text-blue-400 hover:underline">Edit</button>
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
                        <p className="text-sm text-gray-600">No bucket permissions (admin always has full access)</p>
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

      <Modal open={!!editUser} onClose={() => setEditUser(null)} title={`Edit: ${editUser?.full_name}`}>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Role</label>
            <select value={role} onChange={e => setRole(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="admin">Admin</option>
              <option value="manager">Manager</option>
              <option value="user">User</option>
            </select>
          </div>
          <div className="flex items-center gap-3">
            <label className="text-sm text-gray-400">Active</label>
            <input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)} className="rounded" />
          </div>
          <button onClick={save} className="w-full py-2.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 transition-colors">Save Changes</button>
        </div>
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
