import { useEffect, useState } from 'react';
import {
  Building2, Users, Plus, Trash2, ChevronDown, ChevronRight,
  FolderOpen, Mail, Pencil, Check, X,
} from 'lucide-react';
import { api, type OrgMember, type IngestionConfig } from '../../api';
import { useToast } from '../../components/Toast';
import Badge from '../../components/Badge';

interface OrgSummary { id: string; name: string; created_at: string; }

const ROLES = ['viewer', 'user', 'org_admin', 'admin'];
const SOURCE_TYPES = ['directory', 'email'];

// ---------------------------------------------------------------------------
// Helper sub-components
// ---------------------------------------------------------------------------

function SectionHeader({ label }: { label: string }) {
  return (
    <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-3">{label}</h3>
  );
}

function ActionButton({
  onClick, label, variant = 'default', icon: Icon, small = false,
}: {
  onClick: () => void;
  label: string;
  variant?: 'default' | 'danger' | 'primary';
  icon?: React.ElementType;
  small?: boolean;
}) {
  const base = small ? 'px-2 py-1 text-xs' : 'px-3 py-1.5 text-sm';
  const color =
    variant === 'danger' ? 'text-red-400 hover:bg-red-900/30 border-red-800' :
    variant === 'primary' ? 'bg-blue-600 hover:bg-blue-500 text-white border-transparent' :
    'text-gray-300 hover:bg-gray-700 border-gray-700';
  return (
    <button
      onClick={onClick}
      className={`${base} ${color} flex items-center gap-1.5 rounded border transition-colors`}
    >
      {Icon && <Icon size={12} />}{label}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Members panel for a single org
// ---------------------------------------------------------------------------

function MembersPanel({ orgId, allUsers }: { orgId: string; allUsers: { id: string; email: string; full_name: string }[] }) {
  const { show } = useToast();
  const [members, setMembers] = useState<OrgMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [addUserId, setAddUserId] = useState('');
  const [addRole, setAddRole] = useState('user');
  const [showAdd, setShowAdd] = useState(false);
  const [editMemberId, setEditMemberId] = useState<string | null>(null);
  const [editRole, setEditRole] = useState('user');

  const load = () => {
    setLoading(true);
    api.adminListOrgMembers(orgId)
      .then(setMembers)
      .catch(() => show('Failed to load members', 'error'))
      .finally(() => setLoading(false));
  };
  useEffect(load, [orgId]);

  const addMember = async () => {
    if (!addUserId) return;
    try {
      await api.adminAddOrgMember(orgId, addUserId, addRole);
      show('Member added', 'success');
      setShowAdd(false);
      setAddUserId('');
      setAddRole('user');
      load();
    } catch (e) {
      show(String(e), 'error');
    }
  };

  const updateMember = async (userId: string) => {
    try {
      await api.adminUpdateOrgMember(orgId, userId, editRole);
      show('Role updated', 'success');
      setEditMemberId(null);
      load();
    } catch (e) {
      show(String(e), 'error');
    }
  };

  const removeMember = async (userId: string) => {
    if (!confirm('Remove this member?')) return;
    try {
      await api.adminRemoveOrgMember(orgId, userId);
      show('Member removed', 'success');
      load();
    } catch (e) {
      show(String(e), 'error');
    }
  };

  const memberUserIds = new Set(members.map(m => m.user_id));
  const addableUsers = allUsers.filter(u => !memberUserIds.has(u.id));

  if (loading) return <p className="text-gray-500 text-sm py-2">Loading members…</p>;

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <SectionHeader label="Members" />
        <ActionButton onClick={() => setShowAdd(!showAdd)} label="Add Member" icon={Plus} small variant="primary" />
      </div>

      {showAdd && (
        <div className="flex gap-2 mb-4 items-center flex-wrap">
          <select
            value={addUserId}
            onChange={e => setAddUserId(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 flex-1 min-w-[180px]"
          >
            <option value="">Select user…</option>
            {addableUsers.map(u => (
              <option key={u.id} value={u.id}>{u.full_name} ({u.email})</option>
            ))}
          </select>
          <select
            value={addRole}
            onChange={e => setAddRole(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200"
          >
            {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
          <ActionButton onClick={addMember} label="Add" variant="primary" small />
          <ActionButton onClick={() => setShowAdd(false)} label="Cancel" small />
        </div>
      )}

      {members.length === 0 ? (
        <p className="text-gray-500 text-sm">No members yet.</p>
      ) : (
        <div className="space-y-1">
          {members.map(m => (
            <div key={m.user_id} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-gray-800/50 hover:bg-gray-800">
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-gray-200 truncate">{m.full_name}</div>
                <div className="text-xs text-gray-500 truncate">{m.email}</div>
              </div>
              {editMemberId === m.user_id ? (
                <div className="flex items-center gap-2">
                  <select
                    value={editRole}
                    onChange={e => setEditRole(e.target.value)}
                    className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs text-gray-200"
                  >
                    {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                  </select>
                  <button onClick={() => updateMember(m.user_id)} className="text-green-400 hover:text-green-300 p-1"><Check size={13} /></button>
                  <button onClick={() => setEditMemberId(null)} className="text-gray-500 hover:text-gray-300 p-1"><X size={13} /></button>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <Badge color={m.role === 'admin' ? 'blue' : (m.role === 'org_admin' || m.role === 'manager') ? 'yellow' : m.role === 'viewer' ? 'purple' : 'gray'}>{m.role}</Badge>
                  <button
                    onClick={() => { setEditMemberId(m.user_id); setEditRole(m.role); }}
                    className="text-gray-500 hover:text-gray-300 p-1"
                  >
                    <Pencil size={12} />
                  </button>
                  <button onClick={() => removeMember(m.user_id)} className="text-red-500 hover:text-red-400 p-1">
                    <Trash2 size={12} />
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Ingestion config panel for a single org
// ---------------------------------------------------------------------------

function IngestionPanel({ orgId }: { orgId: string }) {
  const { show } = useToast();
  const [configs, setConfigs] = useState<IngestionConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState('');
  const [newType, setNewType] = useState<'directory' | 'email'>('directory');
  const [newConfigStr, setNewConfigStr] = useState('{\n  "watch_directory": "/data/inbox"\n}');
  const [editId, setEditId] = useState<string | null>(null);
  const [editStr, setEditStr] = useState('');
  const [editName, setEditName] = useState('');

  const load = () => {
    setLoading(true);
    api.adminListIngestionConfigs(orgId)
      .then(setConfigs)
      .catch(() => show('Failed to load ingestion configs', 'error'))
      .finally(() => setLoading(false));
  };
  useEffect(load, [orgId]);

  const addConfig = async () => {
    if (!newName) { show('Name is required', 'error'); return; }
    try {
      const config = JSON.parse(newConfigStr);
      await api.adminCreateIngestionConfig(orgId, { name: newName, source_type: newType, config });
      show('Config added', 'success');
      setShowAdd(false);
      setNewName('');
      setNewConfigStr(newType === 'directory'
        ? '{\n  "watch_directory": "/data/inbox"\n}'
        : '{\n  "imap_host": "", "imap_user": "", "imap_password": ""\n}');
      load();
    } catch (e) {
      show(String(e), 'error');
    }
  };

  const toggleActive = async (cfg: IngestionConfig) => {
    try {
      await api.adminUpdateIngestionConfig(orgId, cfg.id, { is_active: !cfg.is_active });
      show(cfg.is_active ? 'Config disabled' : 'Config enabled', 'success');
      load();
    } catch (e) {
      show(String(e), 'error');
    }
  };

  const saveEdit = async () => {
    if (!editId) return;
    try {
      const config = JSON.parse(editStr);
      await api.adminUpdateIngestionConfig(orgId, editId, { name: editName, config });
      show('Config updated', 'success');
      setEditId(null);
      load();
    } catch (e) {
      show(String(e), 'error');
    }
  };

  const deleteConfig = async (cfgId: string) => {
    if (!confirm('Delete this ingestion config?')) return;
    try {
      await api.adminDeleteIngestionConfig(orgId, cfgId);
      show('Config deleted', 'success');
      load();
    } catch (e) {
      show(String(e), 'error');
    }
  };

  const typeIcon = (t: string) => t === 'email' ? <Mail size={13} /> : <FolderOpen size={13} />;

  if (loading) return <p className="text-gray-500 text-sm py-2">Loading ingestion configs…</p>;

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <SectionHeader label="Ingestion Sources" />
        <ActionButton onClick={() => setShowAdd(!showAdd)} label="Add Source" icon={Plus} small variant="primary" />
      </div>

      {showAdd && (
        <div className="bg-gray-800 rounded-lg p-4 mb-4 space-y-3">
          <div className="flex gap-3 flex-wrap">
            <input
              type="text" placeholder="Config name…" value={newName}
              onChange={e => setNewName(e.target.value)}
              className="bg-gray-700 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 flex-1 min-w-[180px]"
            />
            <select
              value={newType}
              onChange={e => {
                const t = e.target.value as 'directory' | 'email';
                setNewType(t);
                setNewConfigStr(t === 'directory'
                  ? '{\n  "watch_directory": "/data/inbox"\n}'
                  : '{\n  "imap_host": "", "imap_user": "", "imap_password": "", "imap_port": "993", "imap_ssl": "true"\n}');
              }}
              className="bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-sm text-gray-200"
            >
              {SOURCE_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <textarea
            rows={5} value={newConfigStr}
            onChange={e => setNewConfigStr(e.target.value)}
            className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm font-mono text-gray-200 resize-y"
            placeholder="JSON config…"
          />
          <div className="flex gap-2">
            <ActionButton onClick={addConfig} label="Save" variant="primary" small />
            <ActionButton onClick={() => setShowAdd(false)} label="Cancel" small />
          </div>
        </div>
      )}

      {configs.length === 0 ? (
        <p className="text-gray-500 text-sm">No ingestion sources configured.</p>
      ) : (
        <div className="space-y-2">
          {configs.map(cfg => (
            <div key={cfg.id} className="bg-gray-800/50 rounded-lg p-3">
              {editId === cfg.id ? (
                <div className="space-y-3">
                  <input
                    type="text" value={editName} onChange={e => setEditName(e.target.value)}
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200"
                  />
                  <textarea
                    rows={5} value={editStr} onChange={e => setEditStr(e.target.value)}
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm font-mono text-gray-200 resize-y"
                  />
                  <div className="flex gap-2">
                    <ActionButton onClick={saveEdit} label="Save" variant="primary" small />
                    <ActionButton onClick={() => setEditId(null)} label="Cancel" small />
                  </div>
                </div>
              ) : (
                <div className="flex items-start gap-3">
                  <div className="text-gray-500 mt-0.5">{typeIcon(cfg.source_type)}</div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-gray-200">{cfg.name}</span>
                      <Badge color={cfg.is_active ? 'green' : 'gray'}>{cfg.is_active ? 'active' : 'disabled'}</Badge>
                      <Badge color="blue">{cfg.source_type}</Badge>
                    </div>
                    <pre className="text-xs text-gray-500 mt-1 overflow-x-auto">
                      {JSON.stringify(cfg.config, null, 2)}
                    </pre>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => { setEditId(cfg.id); setEditName(cfg.name); setEditStr(JSON.stringify(cfg.config, null, 2)); }}
                      className="p-1 text-gray-500 hover:text-gray-300"
                    >
                      <Pencil size={13} />
                    </button>
                    <button
                      onClick={() => toggleActive(cfg)}
                      className={`p-1 ${cfg.is_active ? 'text-yellow-500 hover:text-yellow-400' : 'text-green-500 hover:text-green-400'}`}
                      title={cfg.is_active ? 'Disable' : 'Enable'}
                    >
                      {cfg.is_active ? <X size={13} /> : <Check size={13} />}
                    </button>
                    <button onClick={() => deleteConfig(cfg.id)} className="p-1 text-red-500 hover:text-red-400">
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function OrganizationManagement() {
  const { show } = useToast();
  const [orgs, setOrgs] = useState<OrgSummary[]>([]);
  const [allUsers, setAllUsers] = useState<{ id: string; email: string; full_name: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedOrg, setExpandedOrg] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'members' | 'ingestion'>('members');

  // New org form
  const [showNewOrg, setShowNewOrg] = useState(false);
  const [newOrgName, setNewOrgName] = useState('');

  const load = () => {
    setLoading(true);
    Promise.all([api.adminListOrganizations(), api.getUsers()])
      .then(([os, us]) => {
        setOrgs(os as OrgSummary[]);
        setAllUsers(us.map(u => ({ id: u.id, email: u.email, full_name: u.full_name })));
      })
      .catch(() => show('Failed to load organizations', 'error'))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const createOrg = async () => {
    if (!newOrgName.trim()) return;
    try {
      await api.adminCreateOrganization(newOrgName.trim());
      show('Organization created', 'success');
      setShowNewOrg(false);
      setNewOrgName('');
      load();
    } catch (e) {
      show(String(e), 'error');
    }
  };

  const toggleOrg = (id: string) => {
    setExpandedOrg(prev => prev === id ? null : id);
    setActiveTab('members');
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-gray-500">Loading organizations…</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Organizations</h1>
          <p className="text-gray-500 text-sm mt-1">Manage organizations, members, and ingestion sources.</p>
        </div>
        <ActionButton onClick={() => setShowNewOrg(!showNewOrg)} label="New Organization" icon={Plus} variant="primary" />
      </div>

      {showNewOrg && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 flex gap-3 items-center">
          <input
            type="text" placeholder="Organization name…" value={newOrgName}
            onChange={e => setNewOrgName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && createOrg()}
            className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
            autoFocus
          />
          <ActionButton onClick={createOrg} label="Create" variant="primary" />
          <ActionButton onClick={() => setShowNewOrg(false)} label="Cancel" />
        </div>
      )}

      {orgs.length === 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-12 text-center text-gray-500">
          No organizations found.
        </div>
      ) : (
        <div className="space-y-3">
          {orgs.map(org => (
            <div key={org.id} className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              {/* Header */}
              <button
                onClick={() => toggleOrg(org.id)}
                className="flex items-center gap-3 w-full px-5 py-4 hover:bg-gray-800/50 transition-colors text-left"
              >
                <div className="w-9 h-9 rounded-lg bg-blue-900/30 flex items-center justify-center text-blue-400">
                  <Building2 size={18} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-gray-100">{org.name}</div>
                  <div className="text-xs text-gray-500">Created {new Date(org.created_at).toLocaleDateString()}</div>
                </div>
                {expandedOrg === org.id
                  ? <ChevronDown size={16} className="text-gray-500" />
                  : <ChevronRight size={16} className="text-gray-500" />}
              </button>

              {/* Expanded panel */}
              {expandedOrg === org.id && (
                <div className="border-t border-gray-800">
                  {/* Tabs */}
                  <div className="flex border-b border-gray-800">
                    <button
                      onClick={() => setActiveTab('members')}
                      className={`flex items-center gap-2 px-5 py-3 text-sm font-medium transition-colors ${
                        activeTab === 'members'
                          ? 'text-blue-400 border-b-2 border-blue-500'
                          : 'text-gray-500 hover:text-gray-300'
                      }`}
                    >
                      <Users size={14} /> Members
                    </button>
                    <button
                      onClick={() => setActiveTab('ingestion')}
                      className={`flex items-center gap-2 px-5 py-3 text-sm font-medium transition-colors ${
                        activeTab === 'ingestion'
                          ? 'text-blue-400 border-b-2 border-blue-500'
                          : 'text-gray-500 hover:text-gray-300'
                      }`}
                    >
                      <FolderOpen size={14} /> Ingestion Sources
                    </button>
                  </div>

                  <div className="p-5">
                    {activeTab === 'members' && (
                      <MembersPanel orgId={org.id} allUsers={allUsers} />
                    )}
                    {activeTab === 'ingestion' && (
                      <IngestionPanel orgId={org.id} />
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
