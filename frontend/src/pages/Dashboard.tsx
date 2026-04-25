import { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { FileText, Archive, Clock, Lock, CheckCircle, AlertCircle, Activity } from 'lucide-react';
import { api, type Dashboard, type ActivityItem } from '../api';
import StatCard from '../components/StatCard';
import Badge from '../components/Badge';

function relativeTime(iso: string): string {
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [activity, setActivity] = useState<ActivityItem[]>([]);

  const loadDash = useCallback(() => {
    setLoading(true);
    api.getDashboard(dateFrom || undefined, dateTo || undefined)
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [dateFrom, dateTo]);

  useEffect(() => {
    loadDash();
  }, [loadDash]);

  const loadActivity = useCallback(() => {
    api.getRecentActivity(15).then((r) => setActivity(r.items)).catch(console.error);
  }, []);

  useEffect(() => {
    loadActivity();
    const t = setInterval(loadActivity, 30000);
    return () => clearInterval(t);
  }, [loadActivity]);

  if (loading && !data) return <div className="text-gray-500">Loading dashboard...</div>;
  if (!data) return <div className="text-red-400">Failed to load dashboard</div>;

  const stateColors: Record<string, string> = {
    open: 'text-green-400', pending: 'text-yellow-400', locked: 'text-red-400', closed: 'text-gray-400',
  };

  return (
    <div className="space-y-8">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-1">Overview of your document management system</p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label className="block text-[10px] text-gray-500 uppercase mb-1">From</label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="px-2 py-1.5 rounded-lg bg-gray-900 border border-gray-800 text-gray-300 text-sm"
            />
          </div>
          <div>
            <label className="block text-[10px] text-gray-500 uppercase mb-1">To</label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="px-2 py-1.5 rounded-lg bg-gray-900 border border-gray-800 text-gray-300 text-sm"
            />
          </div>
          <button
            type="button"
            onClick={loadDash}
            className="px-4 py-2 rounded-lg bg-gray-800 text-gray-300 text-sm hover:bg-gray-700"
          >
            Apply
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-7 gap-4">
        <StatCard label="Total Documents" value={data.total_documents} icon={<FileText size={18} />} />
        <StatCard label="Processing" value={data.processing_documents} icon={<AlertCircle size={18} />} />
        <StatCard label="Pending" value={data.pending_documents} icon={<Clock size={18} />} />
        <StatCard label="My Locked" value={data.my_locked_documents} icon={<Lock size={18} />} />
        <StatCard label="Closed" value={data.closed_documents} icon={<CheckCircle size={18} />} />
        <StatCard label="Today" value={data.today_documents} icon={<Clock size={18} />} />
        <StatCard label="This week" value={data.week_documents} icon={<Clock size={18} />} />
      </div>

      {data.bucket_summaries.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
            <Archive size={18} className="text-gray-400" /> Buckets
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {data.bucket_summaries.map(b => (
              <Link key={b.id} to={`/buckets/${b.id}`} className="bg-gray-900 border border-gray-800 rounded-xl p-5 hover:border-gray-700 transition-colors group">
                <div className="flex items-center justify-between mb-3">
                  <span className="font-medium text-white group-hover:text-blue-400 transition-colors">{b.name}</span>
                  <span className="text-sm text-gray-500">{b.total} docs</span>
                </div>
                <div className="grid grid-cols-4 gap-2 text-center">
                  {(['open', 'pending', 'locked', 'closed'] as const).map(st => (
                    <div key={st} className="text-center">
                      <div className={`text-lg font-bold ${stateColors[st]}`}>{b.states[st] || 0}</div>
                      <div className="text-[10px] uppercase tracking-wider text-gray-600">{st}</div>
                    </div>
                  ))}
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}

      {Object.keys(data.classification_distribution).length > 0 && (
        <div>
          <h2 className="text-lg font-semibold text-white mb-4">Classification Distribution</h2>
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <div className="flex flex-wrap gap-4">
              {Object.entries(data.classification_distribution).map(([label, count]) => (
                <div key={label} className="flex items-center gap-2 bg-gray-800/50 rounded-lg px-3 py-2">
                  <Badge value={label} />
                  <span className="text-sm font-medium text-white">{count}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <div>
        <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
          <Activity size={18} className="text-gray-400" /> Recent Activity
        </h2>
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wider">
                <th className="text-left px-4 py-3">Document</th>
                <th className="text-left px-4 py-3">Stage</th>
                <th className="text-left px-4 py-3">Event</th>
                <th className="text-left px-4 py-3">When</th>
              </tr>
            </thead>
            <tbody>
              {activity.map((a) => (
                <tr key={a.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                  <td className="px-4 py-3">
                    <Link to={`/documents/${a.document_id}`} className="text-blue-400 hover:underline">
                      {a.filename || a.document_id}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-gray-400">{a.stage}</td>
                  <td className="px-4 py-3"><Badge value={a.event_type} /></td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{relativeTime(a.timestamp)}</td>
                </tr>
              ))}
              {activity.length === 0 && (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-gray-600">No pipeline activity yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
          <Clock size={18} className="text-gray-400" /> Recent Documents
        </h2>
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wider">
                <th className="text-left px-4 py-3">Filename</th>
                <th className="text-left px-4 py-3">Status</th>
                <th className="text-left px-4 py-3">Classification</th>
                <th className="text-left px-4 py-3">Date</th>
              </tr>
            </thead>
            <tbody>
              {data.recent_documents.map(d => (
                <tr key={d.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                  <td className="px-4 py-3">
                    <Link to={`/documents/${d.id}`} className="text-blue-400 hover:underline">{d.filename}</Link>
                  </td>
                  <td className="px-4 py-3"><Badge value={d.status} /></td>
                  <td className="px-4 py-3 text-gray-400">{[d.classification_label, d.classification_subcategory_label].filter(Boolean).join(' / ') || '---'}</td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{new Date(d.created_at).toLocaleString()}</td>
                </tr>
              ))}
              {data.recent_documents.length === 0 && (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-gray-600">No documents yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
