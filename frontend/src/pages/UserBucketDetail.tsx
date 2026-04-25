import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import { api, type BucketSummary, type BucketDocItem } from '../api';
import Badge from '../components/Badge';

const STATES = ['open', 'pending', 'locked', 'closed'] as const;

export default function UserBucketDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [bucket, setBucket] = useState<BucketSummary | null>(null);
  const [docs, setDocs] = useState<BucketDocItem[]>([]);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState<string>('');
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    if (!id) return;
    try {
      const b = await api.getBucket(id);
      setBucket(b);
      const params: Record<string, string> = { page: String(page), page_size: '20' };
      if (filter) params.workflow_state = filter;
      const res = await api.getBucketDocuments(id, params);
      setDocs(res.documents);
      setTotal(res.total);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [id, filter, page]);

  if (loading) return <div className="text-gray-500">Loading...</div>;
  if (!bucket) return <div className="text-red-400">Bucket not found</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link to="/buckets" className="text-gray-500 hover:text-gray-300"><ArrowLeft size={20} /></Link>
        <div>
          <h1 className="text-2xl font-bold text-white">{bucket.name}</h1>
          {bucket.description && <p className="text-sm text-gray-500 mt-0.5">{bucket.description}</p>}
        </div>
        <button onClick={load} className="ml-auto text-gray-500 hover:text-gray-300"><RefreshCw size={16} /></button>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {STATES.map(st => {
          const colors: Record<string, string> = {
            open: 'border-green-500/30 bg-green-500/5', pending: 'border-yellow-500/30 bg-yellow-500/5',
            locked: 'border-red-500/30 bg-red-500/5', closed: 'border-gray-600/30 bg-gray-600/5',
          };
          const active = filter === st;
          return (
            <button
              key={st} onClick={() => setFilter(filter === st ? '' : st)}
              className={`rounded-xl border p-4 text-center transition-all ${active ? colors[st] + ' ring-1 ring-white/10' : 'border-gray-800 bg-gray-900 hover:border-gray-700'}`}
            >
              <div className="text-2xl font-bold text-white">{bucket.states[st] || 0}</div>
              <div className="text-xs uppercase tracking-wider text-gray-500 mt-1">{st}</div>
            </button>
          );
        })}
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wider">
              <th className="text-left px-4 py-3">Document</th>
              <th className="text-left px-4 py-3">Company</th>
              <th className="text-left px-4 py-3">Client</th>
              <th className="text-left px-4 py-3">Classification</th>
              <th className="text-left px-4 py-3">State</th>
              <th className="text-left px-4 py-3">Locked By</th>
            </tr>
          </thead>
          <tbody>
            {docs.map(d => (
              <tr key={d.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                <td className="px-4 py-3">
                  <Link to={`/documents/${d.document_id}`} state={{ from: `/buckets/${id}` }} className="text-blue-400 hover:underline">{d.filename}</Link>
                </td>
                <td className="px-4 py-3 text-gray-400 text-xs">{d.company_name || '---'}</td>
                <td className="px-4 py-3 text-gray-400 text-xs">{d.client_name || '---'}</td>
                <td className="px-4 py-3 text-gray-400">{[d.classification_label, d.classification_subcategory_label].filter(Boolean).join(' / ') || '---'}</td>
                <td className="px-4 py-3"><Badge value={d.workflow_state} /></td>
                <td className="px-4 py-3 text-gray-400 text-xs">{d.locked_by_name || '---'}</td>
              </tr>
            ))}
            {docs.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-600">No documents in this bucket</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {total > 20 && (
        <div className="flex items-center justify-center gap-2">
          <button onClick={() => setPage(Math.max(1, page - 1))} disabled={page === 1} className="px-3 py-1.5 rounded bg-gray-800 text-gray-400 text-sm hover:bg-gray-700 disabled:opacity-50">Prev</button>
          <span className="text-sm text-gray-500">Page {page} of {Math.ceil(total / 20)}</span>
          <button onClick={() => setPage(page + 1)} disabled={page * 20 >= total} className="px-3 py-1.5 rounded bg-gray-800 text-gray-400 text-sm hover:bg-gray-700 disabled:opacity-50">Next</button>
        </div>
      )}
    </div>
  );
}
