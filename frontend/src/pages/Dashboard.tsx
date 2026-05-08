import { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
  FileText, Archive, Clock, Lock, CheckCircle, AlertCircle,
  TrendingUp, Building2, User, ArrowRight,
} from 'lucide-react';
import { api, type Dashboard, type AuditFeedItem } from '../api';
import Badge from '../components/Badge';

// ---------------------------------------------------------------------------
// SVG chart primitives (zero dependencies)
// ---------------------------------------------------------------------------

function BarChart({ data }: { data: { date: string; count: number }[] }) {
  const max = Math.max(...data.map(d => d.count), 1);
  const W = 600, H = 80, barW = Math.floor(W / data.length) - 1;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" preserveAspectRatio="none">
      {data.map((d, i) => {
        const h = Math.max(2, (d.count / max) * H);
        return (
          <g key={d.date}>
            <rect
              x={i * (W / data.length)}
              y={H - h}
              width={barW}
              height={h}
              rx={2}
              className="fill-blue-500/70 hover:fill-blue-400 transition-colors"
            />
            {d.count > 0 && (
              <title>{d.date}: {d.count}</title>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function DonutRing({
  segments,
}: {
  segments: { value: number; color: string; label: string }[];
}) {
  const total = segments.reduce((s, x) => s + x.value, 0);
  if (total === 0) return <div className="w-24 h-24 rounded-full bg-gray-800 mx-auto" />;

  const R = 36, cx = 44, cy = 44, strokeW = 12;
  const circ = 2 * Math.PI * R;
  let offset = 0;

  return (
    <div className="relative inline-flex items-center justify-center">
      <svg width={88} height={88} viewBox="0 0 88 88">
        <circle cx={cx} cy={cy} r={R} fill="none" stroke="#1f2937" strokeWidth={strokeW} />
        {segments.map((seg, i) => {
          const dash = (seg.value / total) * circ;
          const gap = circ - dash;
          const el = (
            <circle
              key={i}
              cx={cx} cy={cy} r={R}
              fill="none"
              stroke={seg.color}
              strokeWidth={strokeW}
              strokeDasharray={`${dash} ${gap}`}
              strokeDashoffset={-offset}
              strokeLinecap="round"
              style={{ transform: 'rotate(-90deg)', transformOrigin: '50% 50%' }}
            >
              <title>{seg.label}: {seg.value}</title>
            </circle>
          );
          offset += dash;
          return el;
        })}
      </svg>
      <span className="absolute text-lg font-bold text-white">{total}</span>
    </div>
  );
}

function HorizBar({
  label,
  value,
  max,
  color,
}: {
  label: string;
  value: number;
  max: number;
  color: string;
}) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-gray-400 w-20 truncate capitalize">{label}</span>
      <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-gray-400 w-6 text-right">{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Action feed helpers
// ---------------------------------------------------------------------------

const ACTION_LABELS: Record<string, string> = {
  field_updated: 'updated a field',
  entity_resolved: 'resolved entity',
  comment_added: 'added a note',
  comment_edited: 'edited a note',
  comment_deleted: 'deleted a note',
  archived: 'archived document',
  unarchived: 'restored from archive',
  trashed: 'moved to trash',
  restored_from_trash: 'restored from trash',
  classification_updated: 'updated classification',
  entity_field_updated: 'updated entity field',
};

function actionLabel(action: string) {
  return ACTION_LABELS[action] ?? action.replace(/_/g, ' ');
}

function reltime(iso: string) {
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function ActionFeed({ items }: { items: AuditFeedItem[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-gray-600 py-4 text-center">No activity yet</p>;
  }
  return (
    <ul className="space-y-0 divide-y divide-gray-800/50">
      {items.map(item => (
        <li key={item.id} className="flex items-start gap-3 py-2.5">
          <div className="w-1.5 h-1.5 rounded-full bg-blue-500 mt-2 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="text-sm text-gray-300 truncate">
              <span className="text-gray-500">{item.actor ?? 'System'}</span>
              {' '}{actionLabel(item.action)}{' '}
              <Link to={`/documents/${item.document_id}`}
                className="text-blue-400 hover:underline truncate">
                {item.filename ?? item.document_id}
              </Link>
            </div>
            {item.details && (
              <p className="text-xs text-gray-600 truncate mt-0.5">{item.details}</p>
            )}
          </div>
          <span className="text-[11px] text-gray-600 flex-shrink-0 mt-0.5">{reltime(item.created_at)}</span>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Stat card
// ---------------------------------------------------------------------------

function Stat({
  label, value, sub, icon, accent = false,
}: {
  label: string;
  value: number;
  sub?: string;
  icon: React.ReactNode;
  accent?: boolean;
}) {
  return (
    <div className={`bg-gray-900 border rounded-xl p-4 flex items-start gap-3 ${
      accent ? 'border-blue-500/30' : 'border-gray-800'
    }`}>
      <div className="p-2 rounded-lg bg-gray-800 text-gray-400">{icon}</div>
      <div>
        <div className="text-2xl font-bold text-white tabular-nums">{value.toLocaleString()}</div>
        <div className="text-xs text-gray-500 mt-0.5">{label}</div>
        {sub && <div className="text-[11px] text-gray-600 mt-0.5">{sub}</div>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const loadDash = useCallback(() => {
    setLoading(true);
    api.getDashboard(dateFrom || undefined, dateTo || undefined)
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [dateFrom, dateTo]);

  useEffect(() => { loadDash(); }, [loadDash]);

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-500 text-sm">
        Loading dashboard…
      </div>
    );
  }
  if (!data) return <div className="text-red-400">Failed to load dashboard.</div>;

  const confMax = Math.max(...Object.values(data.confidence_buckets), 1);
  const statusTotal = data.status_breakdown.completed + data.status_breakdown.processing + data.status_breakdown.failed;
  const classMax = Math.max(...data.top_classifications.map(c => c.count), 1);
  const entityMax = Math.max(...data.top_entities.map(e => e.doc_count), 1);

  const stateColors: Record<string, string> = {
    open: 'text-green-400', pending: 'text-yellow-400',
    locked: 'text-orange-400', closed: 'text-gray-400',
  };

  return (
    <div className="space-y-7">
      {/* Header + date filter */}
      <div className="flex flex-col sm:flex-row sm:items-end gap-4">
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-white">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-0.5">Overview for your organisation</p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label className="block text-[10px] text-gray-500 uppercase mb-1">From</label>
            <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)}
              className="px-2 py-1.5 rounded-lg bg-gray-900 border border-gray-800 text-gray-300 text-sm" />
          </div>
          <div>
            <label className="block text-[10px] text-gray-500 uppercase mb-1">To</label>
            <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)}
              className="px-2 py-1.5 rounded-lg bg-gray-900 border border-gray-800 text-gray-300 text-sm" />
          </div>
          <button onClick={loadDash}
            className="px-4 py-1.5 rounded-lg bg-gray-800 text-gray-300 text-sm hover:bg-gray-700 transition-colors">
            Apply
          </button>
        </div>
      </div>

      {/* Top stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Total documents"  value={data.total_documents}     icon={<FileText size={16} />} accent />
        <Stat label="Processing"       value={data.processing_documents} icon={<AlertCircle size={16} />} />
        <Stat label="Today"            value={data.today_documents}      icon={<TrendingUp size={16} />} />
        <Stat label="This week"        value={data.week_documents}       icon={<Clock size={16} />} />
      </div>

      {/* Second stats row */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Stat label="Closed (buckets)" value={data.closed_documents}    icon={<CheckCircle size={16} />} />
        <Stat label="Pending review"   value={data.pending_documents}    icon={<Clock size={16} />} />
        <Stat label="My locked docs"   value={data.my_locked_documents}  icon={<Lock size={16} />} />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* Ingestion trend */}
        <div className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-white">Ingestion trend — last 30 days</h2>
            <span className="text-xs text-gray-600">
              {data.daily_counts.reduce((s, d) => s + d.count, 0)} docs
            </span>
          </div>
          <BarChart data={data.daily_counts} />
          <div className="flex justify-between mt-2">
            <span className="text-[10px] text-gray-600">
              {data.daily_counts[0]?.date}
            </span>
            <span className="text-[10px] text-gray-600">
              {data.daily_counts[data.daily_counts.length - 1]?.date}
            </span>
          </div>
        </div>

        {/* Status donut */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 flex flex-col items-center justify-center gap-4">
          <h2 className="text-sm font-semibold text-white self-start">Processing status</h2>
          <DonutRing segments={[
            { value: data.status_breakdown.completed,  color: '#22c55e', label: 'Completed' },
            { value: data.status_breakdown.processing, color: '#3b82f6', label: 'Processing' },
            { value: data.status_breakdown.failed,     color: '#ef4444', label: 'Failed' },
          ]} />
          <div className="w-full space-y-1.5">
            {[
              { key: 'completed',  color: 'bg-green-500',  label: 'Completed' },
              { key: 'processing', color: 'bg-blue-500',   label: 'Processing' },
              { key: 'failed',     color: 'bg-red-500',    label: 'Failed' },
            ].map(s => (
              <div key={s.key} className="flex items-center gap-2 text-xs">
                <div className={`w-2 h-2 rounded-full ${s.color} flex-shrink-0`} />
                <span className="text-gray-400 flex-1">{s.label}</span>
                <span className="tabular-nums text-gray-300">
                  {data.status_breakdown[s.key as keyof typeof data.status_breakdown]}
                </span>
                <span className="text-gray-600 w-8 text-right">
                  {statusTotal > 0
                    ? `${Math.round((data.status_breakdown[s.key as keyof typeof data.status_breakdown] / statusTotal) * 100)}%`
                    : '0%'}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Insights row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">

        {/* Confidence distribution */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-white mb-4">Pipeline confidence</h2>
          <div className="space-y-2.5">
            <HorizBar label="High ≥ 85%"    value={data.confidence_buckets.high}   max={confMax} color="bg-green-500" />
            <HorizBar label="Good 70-85%"   value={data.confidence_buckets.good}   max={confMax} color="bg-blue-500" />
            <HorizBar label="Medium 50-70%" value={data.confidence_buckets.medium} max={confMax} color="bg-yellow-500" />
            <HorizBar label="Low < 50%"     value={data.confidence_buckets.low}    max={confMax} color="bg-red-500" />
          </div>
        </div>

        {/* Top classifications */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-white mb-4">Top document types</h2>
          {data.top_classifications.length === 0 ? (
            <p className="text-sm text-gray-600">No data yet</p>
          ) : (
            <div className="space-y-2.5">
              {data.top_classifications.map(c => (
                <HorizBar key={c.label} label={c.label} value={c.count} max={classMax} color="bg-indigo-500" />
              ))}
            </div>
          )}
        </div>

        {/* Top entities */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-white mb-4">Most active entities</h2>
          {data.top_entities.length === 0 ? (
            <p className="text-sm text-gray-600">No entities yet</p>
          ) : (
            <div className="space-y-2.5">
              {data.top_entities.map(e => (
                <div key={e.id} className="flex items-center gap-2">
                  <span className="text-gray-600">
                    {e.entity_type === 'company' ? <Building2 size={12} /> : <User size={12} />}
                  </span>
                  <Link to={`/admin/entities/${e.id}`}
                    className="text-xs text-gray-300 hover:text-blue-400 flex-1 truncate transition-colors">
                    {e.name}
                  </Link>
                  <span className="text-xs tabular-nums text-gray-500">{e.doc_count} docs</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Buckets */}
      {data.bucket_summaries.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-base font-semibold text-white flex items-center gap-2">
              <Archive size={16} className="text-gray-400" /> Buckets
            </h2>
            <Link to="/buckets" className="text-xs text-blue-400 hover:underline flex items-center gap-1">
              View all <ArrowRight size={11} />
            </Link>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {data.bucket_summaries.map(b => {
              const pct = b.total > 0 ? Math.round((b.states.closed / b.total) * 100) : 0;
              return (
                <Link key={b.id} to={`/buckets/${b.id}`}
                  className="bg-gray-900 border border-gray-800 rounded-xl p-4 hover:border-gray-700 transition-colors group">
                  <div className="flex items-center justify-between mb-3">
                    <span className="font-medium text-white text-sm group-hover:text-blue-400 transition-colors truncate">
                      {b.name}
                    </span>
                    <span className="text-xs text-gray-500 flex-shrink-0">{b.total} docs</span>
                  </div>
                  {/* Progress bar: closed */}
                  <div className="h-1 bg-gray-800 rounded-full mb-3 overflow-hidden">
                    <div className="h-full bg-green-500 rounded-full transition-all"
                      style={{ width: `${pct}%` }} />
                  </div>
                  <div className="grid grid-cols-4 gap-1 text-center">
                    {(['open', 'pending', 'locked', 'closed'] as const).map(st => (
                      <div key={st}>
                        <div className={`text-base font-bold ${stateColors[st]}`}>{b.states[st] || 0}</div>
                        <div className="text-[9px] uppercase tracking-wider text-gray-600">{st}</div>
                      </div>
                    ))}
                  </div>
                </Link>
              );
            })}
          </div>
        </div>
      )}

      {/* Bottom row: activity feed + recent docs */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

        {/* Global activity feed */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-white">Recent activity</h2>
            <Link to="/activity" className="text-xs text-blue-400 hover:underline flex items-center gap-1">
              Full history <ArrowRight size={11} />
            </Link>
          </div>
          <ActionFeed items={data.recent_audit} />
        </div>

        {/* Recent documents */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-white">Recent documents</h2>
            <Link to="/documents" className="text-xs text-blue-400 hover:underline flex items-center gap-1">
              Browse all <ArrowRight size={11} />
            </Link>
          </div>
          <ul className="divide-y divide-gray-800/50">
            {data.recent_documents.length === 0 && (
              <li className="text-sm text-gray-600 py-4 text-center">No documents yet</li>
            )}
            {data.recent_documents.map(d => {
              const conf = d.pipeline_confidence;
              const confColor = conf == null ? 'text-gray-600'
                : conf >= 0.85 ? 'text-green-400'
                : conf >= 0.7  ? 'text-blue-400'
                : conf >= 0.5  ? 'text-yellow-400'
                : 'text-red-400';
              return (
                <li key={d.id} className="flex items-center gap-3 py-2.5">
                  <div className="flex-1 min-w-0">
                    <Link to={`/documents/${d.id}`}
                      className="text-sm text-blue-400 hover:underline truncate block">
                      {d.filename}
                    </Link>
                    <div className="flex items-center gap-2 mt-0.5">
                      <Badge value={d.status} />
                      {d.classification_label && (
                        <span className="text-[11px] text-gray-500">{d.classification_label}</span>
                      )}
                    </div>
                  </div>
                  <div className="text-right flex-shrink-0">
                    {conf != null && (
                      <div className={`text-xs font-medium tabular-nums ${confColor}`}>
                        {Math.round(conf * 100)}%
                      </div>
                    )}
                    <div className="text-[10px] text-gray-600">
                      {new Date(d.created_at).toLocaleDateString()}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </div>
  );
}
