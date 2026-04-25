import { useEffect, useMemo, useState } from 'react';
import { Save, RefreshCw } from 'lucide-react';
import { api, type SystemConfigItem } from '../../api';
import { useToast } from '../../components/Toast';

interface ConfigGroup {
  category: string;
  label: string;
  description: string;
  items: SystemConfigItem[];
}

const GENERAL_CATEGORIES = new Set(['auth', 'ldap', 'email', 'buckets', 'confidence', 'general']);

const CATEGORY_META: Record<string, { label: string; description: string; order: number }> = {
  auth: { label: 'Authentication', description: 'Registration, password policy, verification, and lockout settings.', order: 0 },
  ldap: { label: 'LDAP / Active Directory', description: 'Global LDAP authentication and user provisioning settings.', order: 1 },
  email: { label: 'Email / SMTP', description: 'SMTP configuration used for verification and outgoing emails.', order: 2 },
  buckets: { label: 'Buckets', description: 'Global bucket automation settings.', order: 3 },
  confidence: { label: 'Confidence Scoring', description: 'Global confidence thresholds and scoring weights.', order: 4 },
  general: { label: 'General', description: 'Miscellaneous global settings.', order: 99 },
};

export default function SystemConfigPage() {
  const { show } = useToast();
  const [configs, setConfigs] = useState<SystemConfigItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});

  const load = async () => {
    setLoading(true);
    try {
      const items = await api.getSystemConfig();
      const generalItems = items.filter((item) => GENERAL_CATEGORIES.has(item.category));
      setConfigs(generalItems);
      const edits: Record<string, string> = {};
      for (const item of generalItems) edits[item.key] = item.value;
      setEditing(edits);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const saveKey = async (key: string) => {
    setSaving(prev => ({ ...prev, [key]: true }));
    try {
      await api.updateSystemConfig(key, editing[key]);
      const items = await api.getSystemConfig();
      setConfigs(items);
      show(`Saved ${key}`, 'success');
    } catch (e) {
      console.error(e);
      show(String(e), 'error');
    } finally {
      setSaving(prev => ({ ...prev, [key]: false }));
    }
  };

  const groups: ConfigGroup[] = useMemo(() => {
    const byCategory: Record<string, SystemConfigItem[]> = {};
    for (const c of configs) {
      if (!byCategory[c.category]) byCategory[c.category] = [];
      byCategory[c.category].push(c);
    }
    return Object.entries(byCategory)
      .map(([cat, items]) => {
        const meta = CATEGORY_META[cat] || { label: cat, description: '', order: 99 };
        return { category: cat, label: meta.label, description: meta.description, items };
      })
      .sort((a, b) => (CATEGORY_META[a.category]?.order ?? 99) - (CATEGORY_META[b.category]?.order ?? 99));
  }, [configs]);

  const isToggle = (key: string) => {
    const val = editing[key];
    return val === 'true' || val === 'false';
  };

  const isPasswordField = (key: string) => key.includes('api_key') || key.includes('password') || key.includes('secret');
  const isTextArea = (key: string) => key.includes('weights') || key.includes('filter') || key.includes('dn');

  if (loading) return <div className="text-gray-500">Loading system configuration...</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">General Settings</h1>
          <p className="text-sm text-gray-500 mt-1">Configure authentication, LDAP, email, buckets, and global confidence scoring.</p>
        </div>
        <button onClick={load} className="text-gray-500 hover:text-gray-300"><RefreshCw size={16} /></button>
      </div>

      {groups.map(g => (
        <div key={g.category} className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-white uppercase tracking-wider mb-1">{g.label}</h3>
          {g.description && <p className="text-xs text-gray-500 mb-4">{g.description}</p>}
          <div className="space-y-4">
            {g.items.map(item => {
              const changed = editing[item.key] !== item.value;
              const isSaving = saving[item.key];

              if (isToggle(item.key)) {
                return (
                  <div key={item.key} className="flex items-center justify-between">
                    <div>
                      <div className="text-sm text-gray-300">{item.description || item.key}</div>
                      <div className="text-xs text-gray-600 font-mono">{item.key}</div>
                    </div>
                    <div className="flex items-center gap-3">
                      <button
                        onClick={() => setEditing(prev => ({ ...prev, [item.key]: prev[item.key] === 'true' ? 'false' : 'true' }))}
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                          editing[item.key] === 'true' ? 'bg-blue-600' : 'bg-gray-700'
                        }`}
                      >
                        <span className={`inline-block h-4 w-4 rounded-full bg-white transition-transform ${
                          editing[item.key] === 'true' ? 'translate-x-6' : 'translate-x-1'
                        }`} />
                      </button>
                      {changed && (
                        <button onClick={() => saveKey(item.key)} disabled={isSaving}
                          className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs hover:bg-blue-500 disabled:opacity-50 transition-colors">
                          <Save size={12} /> {isSaving ? 'Saving...' : 'Save'}
                        </button>
                      )}
                    </div>
                  </div>
                );
              }

              return (
                <div key={item.key}>
                  <div className="flex items-center justify-between mb-1.5">
                    <div>
                      <label className="text-sm text-gray-300">{item.description || item.key}</label>
                      <span className="text-xs text-gray-600 font-mono ml-2">{item.key}</span>
                    </div>
                    {changed && (
                      <button onClick={() => saveKey(item.key)} disabled={isSaving}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs hover:bg-blue-500 disabled:opacity-50 transition-colors">
                        <Save size={12} /> {isSaving ? 'Saving...' : 'Save'}
                      </button>
                    )}
                  </div>
                  {isTextArea(item.key) ? (
                    <textarea
                      rows={3}
                      value={editing[item.key] || ''}
                      onChange={e => setEditing(prev => ({ ...prev, [item.key]: e.target.value }))}
                      className="w-full px-3.5 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
                    />
                  ) : (
                    <input
                      type={isPasswordField(item.key) ? 'password' : 'text'}
                      value={editing[item.key] || ''}
                      onChange={e => setEditing(prev => ({ ...prev, [item.key]: e.target.value }))}
                      className="w-full px-3.5 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
