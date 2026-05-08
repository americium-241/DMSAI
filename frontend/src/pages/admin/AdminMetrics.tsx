import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { RefreshCw, Circle, ArrowRight } from 'lucide-react';
import {
  api,
  type NodeHealth,
  type QualityMetrics,
  type GlobalIngestion,
  type LLMUsageStats,
} from '../../api';

// ---------------------------------------------------------------------------
// Tiny SVG chart helpers (no deps)
// ---------------------------------------------------------------------------

function BarChart({
  data,
  color = '#3b82f6',
  height = 80,
}: {
  data: { label: string; value: number }[];
  color?: string;
  height?: number;
}) {
  if (!data.length) return <div className="text-gray-600 text-sm py-4">No data</div>;
  const max = Math.max(...data.map((d) => d.value), 1);
  const w = 100 / data.length;
  return (
    <svg viewBox={`0 0 100 ${height}`} className="w-full" style={{ height }}>
      {data.map((d, i) => {
        const barH = (d.value / max) * (height - 16);
        const x = i * w + w * 0.1;
        const bw = w * 0.8;
        return (
          <g key={i}>
            <rect x={x} y={height - 16 - barH} width={bw} height={barH} fill={color} rx="1" opacity="0.85" />
            {data.length <= 14 && (
              <text x={x + bw / 2} y={height - 2} textAnchor="middle" fontSize="3" fill="#6b7280">
                {d.label.slice(-5)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function HorizBar({ label, value, max, color = 'bg-blue-600/80' }: { label: string; value: number; max: number; color?: string }) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div>
      <div className="flex justify-between text-xs text-gray-400 mb-0.5">
        <span className="truncate max-w-[70%]">{label}</span>
        <span className="text-gray-300 ml-2">{value.toLocaleString()}</span>
      </div>
      <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${Math.max(pct, 2)}%` }} />
      </div>
    </div>
  );
}

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
      <div className="text-xs text-gray-500 uppercase tracking-wider">{label}</div>
      <div className="text-2xl font-bold text-white mt-1">{value}</div>
      {sub && <div className="text-xs text-gray-600 mt-1">{sub}</div>}
    </div>
  );
}

function fmtK(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

// ---------------------------------------------------------------------------
// Pipeline tab
// ---------------------------------------------------------------------------

const NODE_ORDER = [
  'ingestion', 'conversion', 'storage', 'ocr',
  'entity_extraction', 'classification', 'entity_resolution', 'field_extraction',
];

const NODE_LABELS: Record<string, string> = {
  ingestion: 'Ingestion', conversion: 'Conversion', storage: 'Storage', ocr: 'OCR',
  entity_extraction: 'Entity Extraction', classification: 'Classification',
  entity_resolution: 'Entity Resolution', field_extraction: 'Field Extraction',
};

function PipelineTab() {
  const [health, setHealth] = useState<Record<string, NodeHealth>>({});
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api.getPipelineHealth().then(setHealth).catch(console.error).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const healthyCount = NODE_ORDER.filter((n) => health[n]?.status === 'healthy').length;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-400">{healthyCount}/{NODE_ORDER.length} nodes healthy</p>
        <button
          onClick={load} disabled={loading}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gray-800 text-gray-300 text-sm hover:bg-gray-700 transition-colors"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      <div className="flex flex-wrap gap-3 items-center">
        {NODE_ORDER.map((name, i) => {
          const h = health[name];
          const isUp = h?.status === 'healthy';
          return (
            <div key={name} className="flex items-center gap-3">
              <div className={`bg-gray-900 border rounded-xl p-4 w-44 ${isUp ? 'border-green-500/30' : 'border-red-500/30'}`}>
                <div className="flex items-center gap-2 mb-2">
                  <Circle size={8} className={isUp ? 'fill-green-400 text-green-400' : 'fill-red-400 text-red-400'} />
                  <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${isUp ? 'bg-green-500/15 text-green-400' : 'bg-red-500/15 text-red-400'}`}>
                    {h?.status || 'unknown'}
                  </span>
                </div>
                <div className="text-sm font-medium text-white">{NODE_LABELS[name] || name}</div>
                {h?.queue && (
                  <div className="mt-2 space-y-0.5 text-xs">
                    <div className="flex justify-between text-gray-500">
                      <span>Pending</span><span className="text-gray-300">{h.queue.pending}</span>
                    </div>
                    <div className="flex justify-between text-gray-500">
                      <span>Processing</span><span className="text-gray-300">{h.queue.processing}</span>
                    </div>
                    <div className="flex justify-between text-gray-500">
                      <span>DLQ</span>
                      <span className={h.queue.dead_letter > 0 ? 'text-red-400' : 'text-gray-300'}>{h.queue.dead_letter}</span>
                    </div>
                  </div>
                )}
              </div>
              {i < NODE_ORDER.length - 1 && <ArrowRight size={16} className="text-gray-700 flex-shrink-0" />}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Global Ingestion tab
// ---------------------------------------------------------------------------

function IngestionTab() {
  const [data, setData] = useState<GlobalIngestion | null>(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.getGlobalIngestion(days).then(setData).catch(console.error).finally(() => setLoading(false));
  }, [days]);

  if (loading && !data) return <div className="text-gray-500">Loading ingestion data…</div>;
  if (!data) return null;

  const maxDay = Math.max(...data.daily_counts.map((d) => d.count), 1);
  const statusColors: Record<string, string> = {
    COMPLETED: 'bg-green-500/70', FAILED: 'bg-red-500/70', PROCESSING: 'bg-yellow-500/70',
  };
  const totalOrgDocs = data.per_org.reduce((s, o) => s + o.count, 0) || 1;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        {[30, 90].map((d) => (
          <button
            key={d} onClick={() => setDays(d)}
            className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${days === d ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}
          >
            {d}d
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total documents" value={data.total_documents.toLocaleString()} sub="all time · all orgs" />
        <StatCard label="In period" value={data.daily_counts.reduce((s, d) => s + d.count, 0).toLocaleString()} sub={`last ${days} days`} />
        <StatCard label="Completed" value={(data.status_breakdown['COMPLETED'] ?? 0).toLocaleString()} />
        <StatCard label="Failed" value={(data.status_breakdown['FAILED'] ?? 0).toLocaleString()} />
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-300 mb-4">Daily ingestion — last {days} days</h2>
        {data.daily_counts.length > 0 ? (
          <BarChart
            data={data.daily_counts.map((d) => ({ label: d.date, value: d.count }))}
            color="#3b82f6"
            height={100}
          />
        ) : (
          <div className="text-gray-600 text-sm py-6 text-center">No data for this period</div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-300 mb-4">Status breakdown</h2>
          <div className="space-y-3">
            {Object.entries(data.status_breakdown).map(([status, count]) => (
              <HorizBar key={status} label={status} value={count} max={data.total_documents} color={statusColors[status] || 'bg-gray-500/70'} />
            ))}
          </div>
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-300 mb-4">Per organization</h2>
          <div className="space-y-3">
            {data.per_org.slice(0, 8).map((o) => (
              <HorizBar key={o.org_id} label={o.org_name} value={o.count} max={totalOrgDocs} color="bg-purple-500/70" />
            ))}
            {data.per_org.length === 0 && <p className="text-gray-600 text-sm">No org data</p>}
          </div>
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-300 mb-4">Top classifications</h2>
          <div className="space-y-3">
            {data.top_classifications.slice(0, 8).map((c) => (
              <HorizBar key={c.label} label={c.label} value={c.count} max={data.top_classifications[0]?.count ?? 1} color="bg-teal-500/70" />
            ))}
            {data.top_classifications.length === 0 && <p className="text-gray-600 text-sm">No data</p>}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// LLM Usage tab
// ---------------------------------------------------------------------------

const STAGE_COLORS: Record<string, string> = {
  ocr: 'bg-orange-500/70',
  classification: 'bg-blue-500/70',
  entity_extraction: 'bg-purple-500/70',
  entity_resolution: 'bg-pink-500/70',
  field_extraction: 'bg-teal-500/70',
  unknown: 'bg-gray-500/70',
};

function LLMUsageTab() {
  const [data, setData] = useState<LLMUsageStats | null>(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.getLLMUsageStats(days).then(setData).catch(console.error).finally(() => setLoading(false));
  }, [days]);

  if (loading && !data) return <div className="text-gray-500">Loading LLM usage…</div>;
  if (!data) return null;

  const maxDay = Math.max(...data.daily_tokens.map((d) => d.prompt_tokens + d.completion_tokens), 1);
  const maxStage = Math.max(...data.by_stage.map((s) => s.total_tokens), 1);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        {[7, 30, 90].map((d) => (
          <button
            key={d} onClick={() => setDays(d)}
            className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${days === d ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}
          >
            {d}d
          </button>
        ))}
      </div>

      {data.total.calls === 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-10 text-center">
          <p className="text-gray-500 text-sm">No LLM usage recorded yet.</p>
          <p className="text-gray-600 text-xs mt-2">Token data is collected from new pipeline runs after enabling this feature.</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard label="Total tokens (all time)" value={fmtK(data.total.total_tokens)} sub={`${data.total.calls.toLocaleString()} calls`} />
            <StatCard label={`Tokens (last ${days}d)`} value={fmtK(data.period.total_tokens)} sub={`${data.period.calls.toLocaleString()} calls`} />
            <StatCard label="Prompt tokens (all)" value={fmtK(data.total.prompt_tokens)} sub="input" />
            <StatCard label="Completion tokens (all)" value={fmtK(data.total.completion_tokens)} sub="output" />
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-gray-300 mb-4">Daily token usage — last {days} days</h2>
            {data.daily_tokens.length > 0 ? (
              <div className="space-y-2">
                <BarChart
                  data={data.daily_tokens.map((d) => ({
                    label: d.date,
                    value: d.prompt_tokens + d.completion_tokens,
                  }))}
                  color="#8b5cf6"
                  height={100}
                />
                <div className="flex gap-4 text-xs text-gray-500 justify-end">
                  <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-violet-500 inline-block" /> total tokens / day</span>
                </div>
              </div>
            ) : (
              <div className="text-gray-600 text-sm py-6 text-center">No data for this period</div>
            )}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-gray-300 mb-4">By pipeline stage</h2>
              <div className="space-y-3">
                {data.by_stage.map((s) => (
                  <HorizBar
                    key={s.stage} label={s.stage} value={s.total_tokens}
                    max={maxStage} color={STAGE_COLORS[s.stage] || 'bg-gray-500/70'}
                  />
                ))}
                {data.by_stage.length === 0 && <p className="text-gray-600 text-sm">No data</p>}
              </div>
            </div>

            <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-gray-300 mb-4">By provider</h2>
              <div className="space-y-3">
                {data.by_provider.map((p) => (
                  <HorizBar
                    key={p.provider} label={p.provider} value={p.total_tokens}
                    max={data.total.total_tokens || 1} color="bg-blue-500/70"
                  />
                ))}
              </div>
              <div className="mt-5">
                <h2 className="text-sm font-semibold text-gray-300 mb-3">By call type</h2>
                <div className="space-y-3">
                  {data.by_call_type.map((t) => (
                    <HorizBar
                      key={t.call_type} label={t.call_type} value={t.total_tokens}
                      max={data.total.total_tokens || 1} color="bg-teal-500/70"
                    />
                  ))}
                </div>
              </div>
            </div>

            <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-gray-300 mb-4">By model</h2>
              <div className="space-y-3">
                {data.by_model.map((m) => (
                  <HorizBar
                    key={m.model} label={m.model} value={m.total_tokens}
                    max={data.by_model[0]?.total_tokens ?? 1} color="bg-pink-500/70"
                  />
                ))}
                {data.by_model.length === 0 && <p className="text-gray-600 text-sm">No data</p>}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Quality tab  (existing quality metrics, condensed)
// ---------------------------------------------------------------------------

const DIST_KEYS = ['0.0-0.2', '0.2-0.4', '0.4-0.6', '0.6-0.8', '0.8-1.0'] as const;

function QualityTab() {
  const [data, setData] = useState<QualityMetrics | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getQualityMetrics().then(setData).catch(console.error).finally(() => setLoading(false));
  }, []);

  if (loading && !data) return <div className="text-gray-500">Loading quality metrics…</div>;
  if (!data) return null;

  const maxBar = Math.max(...DIST_KEYS.map((k) => data.confidence_distribution[k] || 0), 1);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total corrections" value={data.total_corrections.toLocaleString()} />
        <StatCard
          label="Correction rate"
          value={`${(data.correction_rate * 100).toFixed(2)}%`}
          sub="per document"
        />
        <StatCard
          label="Avg confidence"
          value={data.avg_pipeline_confidence != null ? `${(data.avg_pipeline_confidence * 100).toFixed(1)}%` : 'N/A'}
        />
        <StatCard label="Documents" value={data.total_documents.toLocaleString()} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-300 mb-4">Confidence distribution</h2>
          <div className="space-y-3">
            {DIST_KEYS.map((k) => {
              const v = data.confidence_distribution[k] || 0;
              return (
                <HorizBar key={k} label={k} value={v} max={maxBar} color="bg-blue-600/80" />
              );
            })}
          </div>
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-300 mb-4">Corrections by type</h2>
          <div className="flex flex-wrap gap-2 mb-4">
            {Object.entries(data.corrections_by_type).map(([t, n]) => (
              <span key={t} className="px-3 py-1.5 rounded-lg bg-gray-800 text-sm text-gray-300">
                {t}: <span className="text-white font-medium">{n}</span>
              </span>
            ))}
            {Object.keys(data.corrections_by_type).length === 0 && (
              <span className="text-gray-600 text-sm">No corrections yet</span>
            )}
          </div>
          <h2 className="text-sm font-semibold text-gray-300 mb-3">Most corrected fields</h2>
          <table className="w-full text-sm">
            <tbody>
              {data.most_corrected_fields.map((r) => (
                <tr key={String(r.field_name)} className="border-b border-gray-800/50">
                  <td className="py-1.5 font-mono text-xs text-gray-300">{r.field_name ?? 'N/A'}</td>
                  <td className="py-1.5 text-right text-gray-400">{r.count}</td>
                </tr>
              ))}
              {data.most_corrected_fields.length === 0 && (
                <tr><td colSpan={2} className="py-4 text-gray-600 text-center text-sm">No field corrections</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {data.weekly_confidence.length > 0 && (
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-gray-300 mb-4">Weekly avg confidence</h2>
            <table className="w-full text-sm">
              <tbody>
                {data.weekly_confidence.slice(-12).map((w) => (
                  <tr key={String(w.week)} className="border-b border-gray-800/50">
                    <td className="py-1.5 text-gray-400">{w.week ?? 'N/A'}</td>
                    <td className="py-1.5 text-gray-300 text-right">
                      {w.avg_pipeline_confidence != null ? `${(w.avg_pipeline_confidence * 100).toFixed(1)}%` : 'N/A'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-300 mb-4">Classification changes</h2>
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {data.classification_changes.map((c, i) => (
              <div key={i} className="text-sm text-gray-400 flex items-center gap-2 flex-wrap">
                <span className="text-gray-500">{c.from ?? 'none'}</span>
                <span>→</span>
                <span className="text-gray-300">{c.to ?? 'none'}</span>
                <span className="text-xs bg-gray-800 px-2 py-0.5 rounded">{c.count}x</span>
              </div>
            ))}
            {data.classification_changes.length === 0 && (
              <p className="text-gray-600 text-sm">No classification corrections</p>
            )}
          </div>
        </div>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-300 mb-4">Recent corrections</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <tbody>
              {data.recent_corrections.map((r) => (
                <tr key={r.id} className="border-b border-gray-800/50">
                  <td className="py-2 text-gray-500 whitespace-nowrap text-xs">{new Date(r.created_at).toLocaleString()}</td>
                  <td className="py-2 text-gray-400">{r.corrected_by_name}</td>
                  <td className="py-2 text-gray-400">{r.field_type}</td>
                  <td className="py-2">
                    <Link to={`/documents/${r.document_id}`} className="text-blue-400 hover:underline text-xs font-mono">
                      {r.document_id.slice(0, 8)}…
                    </Link>
                  </td>
                  <td className="py-2 text-gray-400 text-xs max-w-[240px] truncate" title={`${r.original_value} → ${r.corrected_value}`}>
                    {r.original_value ?? 'none'} → {r.corrected_value ?? 'none'}
                  </td>
                </tr>
              ))}
              {data.recent_corrections.length === 0 && (
                <tr><td colSpan={5} className="py-8 text-center text-gray-600">No corrections recorded</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Root page — tabs
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'pipeline', label: 'Pipeline' },
  { id: 'ingestion', label: 'Ingestion' },
  { id: 'llm', label: 'LLM Usage' },
  { id: 'quality', label: 'Quality' },
] as const;

type TabId = typeof TABS[number]['id'];

export default function AdminMetricsPage() {
  const [tab, setTab] = useState<TabId>('pipeline');

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">System Metrics</h1>
        <p className="text-sm text-gray-500 mt-1">Pipeline health, ingestion volume, LLM consumption, and quality analytics</p>
      </div>

      <div className="flex gap-1 border-b border-gray-800">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
              tab === t.id
                ? 'border-blue-500 text-white'
                : 'border-transparent text-gray-500 hover:text-gray-300'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div>
        {tab === 'pipeline'  && <PipelineTab />}
        {tab === 'ingestion' && <IngestionTab />}
        {tab === 'llm'       && <LLMUsageTab />}
        {tab === 'quality'   && <QualityTab />}
      </div>
    </div>
  );
}
