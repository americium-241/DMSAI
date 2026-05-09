import { useEffect, useMemo, useState } from 'react';
import { Loader, Save, X } from 'lucide-react';
import {
  api,
  type AccessMatrixSnapshot,
  type AccessMatrixOrg,
  type AccessMatrixBucket,
} from '../api';

const ROLE_OPTIONS = [
  { value: '', label: 'Not a member' },
  { value: 'viewer', label: 'Viewer' },
  { value: 'user', label: 'User' },
  { value: 'org_admin', label: 'Org admin' },
  { value: 'admin', label: 'Admin' },
];

const PERM_OPTIONS = [
  { value: '', label: '—' },
  { value: 'view', label: 'view' },
  { value: 'edit', label: 'edit' },
  { value: 'admin', label: 'admin' },
];

/**
 * Phase 5 permission matrix editor — opened from the admin Users page.
 *
 * Lays out every visible org as a panel.  Inside each panel:
 *   - dropdown for the user's membership role in that org
 *   - one row per bucket with a permission dropdown
 *
 * Bucket grants in an org where the user has no membership automatically
 * promote them to a `viewer` of that org on save (handled server-side).
 */
export default function AccessMatrixEditor({
  userId,
  userLabel,
  onClose,
  onSaved,
  showToast,
}: {
  userId: string;
  userLabel: string;
  onClose: () => void;
  onSaved?: () => void;
  showToast: (msg: string, type?: 'success' | 'error' | 'info') => void;
}) {
  const [snapshot, setSnapshot] = useState<AccessMatrixSnapshot | null>(null);
  const [draft, setDraft] = useState<AccessMatrixOrg[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [filter, setFilter] = useState('');

  useEffect(() => {
    setLoading(true);
    api
      .getUserAccessMatrix(userId)
      .then(snap => {
        setSnapshot(snap);
        // Deep clone so edits don't mutate the original
        setDraft(JSON.parse(JSON.stringify(snap.matrix)));
      })
      .catch(e => showToast(String(e), 'error'))
      .finally(() => setLoading(false));
  }, [userId]);

  const setMembership = (orgId: string, role: string) => {
    setDraft(d => d.map(o => o.organization_id === orgId
      ? { ...o, membership_role: role || null }
      : o,
    ));
  };

  const setBucketPerm = (orgId: string, bucketId: string, perm: string) => {
    setDraft(d => d.map(o => {
      if (o.organization_id !== orgId) return o;
      return {
        ...o,
        buckets: o.buckets.map(b =>
          b.bucket_id === bucketId ? { ...b, permission: perm || null } : b,
        ),
      };
    }));
  };

  const computeChanges = useMemo(() => {
    if (!snapshot) return { memberships: [], bucket_grants: [] };
    const original = new Map(snapshot.matrix.map(o => [o.organization_id, o]));
    const memberships: Array<{ organization_id: string; role: string | null }> = [];
    const bucket_grants: Array<{ bucket_id: string; permission: string | null }> = [];
    for (const orgEdit of draft) {
      const orig = original.get(orgEdit.organization_id);
      if (!orig) continue;
      if ((orig.membership_role || null) !== (orgEdit.membership_role || null)) {
        memberships.push({
          organization_id: orgEdit.organization_id,
          role: orgEdit.membership_role,
        });
      }
      const origBuckets = new Map(orig.buckets.map(b => [b.bucket_id, b]));
      for (const b of orgEdit.buckets) {
        const ob = origBuckets.get(b.bucket_id);
        if (!ob) continue;
        if ((ob.permission || null) !== (b.permission || null)) {
          bucket_grants.push({
            bucket_id: b.bucket_id,
            permission: b.permission,
          });
        }
      }
    }
    return { memberships, bucket_grants };
  }, [draft, snapshot]);

  const dirty = computeChanges.memberships.length + computeChanges.bucket_grants.length;

  const save = async () => {
    if (!dirty) {
      showToast('No changes to save', 'info');
      return;
    }
    setSaving(true);
    try {
      await api.updateUserAccessMatrix(userId, computeChanges);
      showToast(`Saved ${dirty} permission change(s)`, 'success');
      onSaved?.();
      onClose();
    } catch (e) {
      showToast(String(e), 'error');
    } finally {
      setSaving(false);
    }
  };

  const visibleOrgs = useMemo(() => {
    if (!filter.trim()) return draft;
    const q = filter.toLowerCase();
    return draft.filter(o =>
      o.organization_name.toLowerCase().includes(q) ||
      o.buckets.some(b => b.bucket_name.toLowerCase().includes(q)),
    );
  }, [draft, filter]);

  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-gray-900 border border-gray-800 rounded-xl shadow-2xl w-full max-w-5xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-800 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-white">Permissions matrix</h2>
            <p className="text-xs text-gray-500 mt-0.5">{userLabel}</p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-300 p-1 rounded-lg hover:bg-gray-800"
          >
            <X size={18} />
          </button>
        </div>

        {/* Filter */}
        <div className="px-6 py-3 border-b border-gray-800">
          <input
            type="text"
            placeholder="Filter organizations or buckets..."
            value={filter}
            onChange={e => setFilter(e.target.value)}
            className="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-gray-500">
              <Loader className="animate-spin mr-2" size={20} /> Loading matrix...
            </div>
          ) : visibleOrgs.length === 0 ? (
            <p className="text-sm text-gray-500 text-center py-8">No organizations match your filter.</p>
          ) : (
            <div className="space-y-4">
              {visibleOrgs.map(org => (
                <OrgPanel
                  key={org.organization_id}
                  org={org}
                  onSetMembership={role => setMembership(org.organization_id, role)}
                  onSetBucketPerm={(bucketId, perm) => setBucketPerm(org.organization_id, bucketId, perm)}
                />
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-800 flex items-center justify-between">
          <div className="text-xs text-gray-500">
            {dirty === 0 ? 'No pending changes' : `${dirty} pending change${dirty === 1 ? '' : 's'}`}
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-sm text-gray-400 hover:text-gray-200 hover:bg-gray-800 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={save}
              disabled={saving || dirty === 0}
              className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
            >
              <Save size={14} /> {saving ? 'Saving...' : 'Save changes'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function OrgPanel({
  org,
  onSetMembership,
  onSetBucketPerm,
}: {
  org: AccessMatrixOrg;
  onSetMembership: (role: string) => void;
  onSetBucketPerm: (bucketId: string, permission: string) => void;
}) {
  return (
    <div className="bg-gray-800/40 border border-gray-800 rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between bg-gray-800/30">
        <div>
          <div className="text-sm font-semibold text-white">{org.organization_name}</div>
          <div className="text-xs text-gray-500">{org.buckets.length} bucket(s)</div>
        </div>
        <div>
          <label className="text-xs text-gray-500 mr-2">Membership:</label>
          <select
            value={org.membership_role || ''}
            onChange={e => onSetMembership(e.target.value)}
            className="px-2.5 py-1.5 rounded-md bg-gray-800 border border-gray-700 text-white text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            {ROLE_OPTIONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        </div>
      </div>
      {org.buckets.length === 0 ? (
        <p className="px-4 py-3 text-xs text-gray-500">This organization has no buckets yet.</p>
      ) : (
        <div className="divide-y divide-gray-800/60">
          {org.buckets.map(b => <BucketRow key={b.bucket_id} bucket={b} onChange={p => onSetBucketPerm(b.bucket_id, p)} />)}
        </div>
      )}
    </div>
  );
}

function BucketRow({ bucket, onChange }: { bucket: AccessMatrixBucket; onChange: (p: string) => void }) {
  return (
    <div className="px-4 py-2 flex items-center justify-between hover:bg-gray-800/30">
      <div className="text-sm text-gray-300">{bucket.bucket_name}</div>
      <select
        value={bucket.permission || ''}
        onChange={e => onChange(e.target.value)}
        className="px-2 py-1 rounded-md bg-gray-800 border border-gray-700 text-white text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
      >
        {PERM_OPTIONS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
      </select>
    </div>
  );
}
