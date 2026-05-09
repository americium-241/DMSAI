import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Archive, Search, Globe, Building2 } from 'lucide-react';
import { api, type BucketSummary } from '../api';
import { useAuth } from '../auth';

const stateColors: Record<string, string> = {
  open: 'text-green-400', pending: 'text-yellow-400', locked: 'text-red-400', closed: 'text-gray-400',
};

export default function UserBucketsPage() {
  const { user } = useAuth();
  const [buckets, setBuckets] = useState<BucketSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');
  const [acrossOrgs, setAcrossOrgs] = useState(false);

  // Show the toggle only when the user actually has more than one org membership.
  const hasMultipleOrgs = (user?.organizations?.length || 0) > 1;

  useEffect(() => {
    setLoading(true);
    api.getBuckets({ acrossOrgs }).then(setBuckets).catch(console.error).finally(() => setLoading(false));
  }, [acrossOrgs]);

  const filtered = useMemo(() => {
    if (!filter) return buckets;
    const q = filter.toLowerCase();
    return buckets.filter(b =>
      b.name.toLowerCase().includes(q) ||
      (b.organization_name?.toLowerCase().includes(q) ?? false),
    );
  }, [buckets, filter]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Buckets</h1>
          <p className="text-sm text-gray-500 mt-1">Document groupings with workflow states</p>
        </div>
        <div className="flex items-center gap-3">
          {hasMultipleOrgs && (
            <div className="flex bg-gray-900 border border-gray-800 rounded-lg p-0.5">
              <button
                onClick={() => setAcrossOrgs(false)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                  !acrossOrgs ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                <Building2 size={12} /> Current org
              </button>
              <button
                onClick={() => setAcrossOrgs(true)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                  acrossOrgs ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                <Globe size={12} /> All my orgs
              </button>
            </div>
          )}
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
            <input
              value={filter} onChange={e => setFilter(e.target.value)}
              className="pl-9 pr-4 py-2 rounded-lg bg-gray-900 border border-gray-800 text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 w-56"
              placeholder="Filter buckets..."
            />
          </div>
        </div>
      </div>

      {loading ? (
        <div className="text-gray-500">Loading...</div>
      ) : filtered.length === 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-12 text-center">
          <Archive size={40} className="mx-auto text-gray-700 mb-4" />
          <p className="text-gray-500">{buckets.length === 0 ? 'No buckets available.' : 'No buckets match your filter.'}</p>
        </div>
      ) : (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wider">
                <th className="text-left px-4 py-3">Name</th>
                {acrossOrgs && <th className="text-left px-4 py-3">Organization</th>}
                <th className="text-left px-4 py-3">Description</th>
                <th className="text-center px-4 py-3">Total</th>
                <th className="text-center px-4 py-3">Open</th>
                <th className="text-center px-4 py-3">Pending</th>
                <th className="text-center px-4 py-3">Locked</th>
                <th className="text-center px-4 py-3">Closed</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(b => (
                <tr key={b.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                  <td className="px-4 py-3">
                    <Link to={`/buckets/${b.id}`} className="text-blue-400 hover:underline font-medium">{b.name}</Link>
                  </td>
                  {acrossOrgs && (
                    <td className="px-4 py-3 text-xs text-gray-400">
                      {b.organization_name || <span className="text-gray-600">—</span>}
                    </td>
                  )}
                  <td className="px-4 py-3 text-gray-500 text-xs max-w-xs truncate">{b.description || '---'}</td>
                  <td className="px-4 py-3 text-center text-white font-medium">{b.total}</td>
                  <td className={`px-4 py-3 text-center font-medium ${stateColors.open}`}>{b.states.open || 0}</td>
                  <td className={`px-4 py-3 text-center font-medium ${stateColors.pending}`}>{b.states.pending || 0}</td>
                  <td className={`px-4 py-3 text-center font-medium ${stateColors.locked}`}>{b.states.locked || 0}</td>
                  <td className={`px-4 py-3 text-center font-medium ${stateColors.closed}`}>{b.states.closed || 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
