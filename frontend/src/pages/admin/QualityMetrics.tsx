import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, type QualityMetrics } from '../../api';

const DIST_KEYS = ['0.0-0.2', '0.2-0.4', '0.4-0.6', '0.6-0.8', '0.8-1.0'] as const;

export default function QualityMetricsPage() {
  const [data, setData] = useState<QualityMetrics | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.getQualityMetrics()
      .then(setData)
      .catch((e: Error) => {
        setErr(e.message);
        console.error(e);
      });
  }, []);

  if (err) return <div className="text-red-400">{err}</div>;
  if (!data) return <div className="text-gray-500">Loading quality metrics...</div>;

  const maxBar = Math.max(...DIST_KEYS.map((k) => data.confidence_distribution[k] || 0), 1);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">Quality Metrics</h1>
        <p className="text-sm text-gray-500 mt-1">Corrections, confidence trends, and field-level feedback</p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <div className="text-xs text-gray-500 uppercase tracking-wider">Total corrections</div>
          <div className="text-2xl font-bold text-white mt-1">{data.total_corrections}</div>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <div className="text-xs text-gray-500 uppercase tracking-wider">Correction rate</div>
          <div className="text-2xl font-bold text-white mt-1">{(data.correction_rate * 100).toFixed(2)}%</div>
          <div className="text-xs text-gray-600 mt-1">per document</div>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <div className="text-xs text-gray-500 uppercase tracking-wider">Avg pipeline confidence</div>
          <div className="text-2xl font-bold text-white mt-1">
            {data.avg_pipeline_confidence != null ? `${(data.avg_pipeline_confidence * 100).toFixed(1)}%` : 'N/A'}
          </div>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <div className="text-xs text-gray-500 uppercase tracking-wider">Documents</div>
          <div className="text-2xl font-bold text-white mt-1">{data.total_documents}</div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h2 className="text-lg font-semibold text-white mb-4">Confidence distribution</h2>
          <div className="space-y-3">
            {DIST_KEYS.map((k) => {
              const v = data.confidence_distribution[k] || 0;
              const w = maxBar > 0 ? (v / maxBar) * 100 : 0;
              return (
                <div key={k}>
                  <div className="flex justify-between text-xs text-gray-400 mb-1">
                    <span>{k}</span>
                    <span>{v}</span>
                  </div>
                  <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                    <div className="h-full bg-blue-600/80 rounded-full transition-all" style={{ width: `${Math.max(w, 2)}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h2 className="text-lg font-semibold text-white mb-4">Corrections by type</h2>
          <div className="flex flex-wrap gap-2">
            {Object.entries(data.corrections_by_type).map(([t, n]) => (
              <span key={t} className="px-3 py-1.5 rounded-lg bg-gray-800 text-sm text-gray-300">
                {t}: <span className="text-white font-medium">{n}</span>
              </span>
            ))}
            {Object.keys(data.corrections_by_type).length === 0 && (
              <span className="text-gray-600 text-sm">No corrections yet</span>
            )}
          </div>
        </div>
      </div>

      {data.weekly_confidence.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h2 className="text-lg font-semibold text-white mb-4">Weekly average pipeline confidence</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <tbody>
                {data.weekly_confidence.map((w) => (
                  <tr key={String(w.week)} className="border-b border-gray-800/50">
                    <td className="py-2 text-gray-300">{w.week ?? 'N/A'}</td>
                    <td className="py-2 text-gray-400">
                      {w.avg_pipeline_confidence != null ? `${(w.avg_pipeline_confidence * 100).toFixed(1)}%` : 'N/A'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h2 className="text-lg font-semibold text-white mb-4">Most corrected fields</h2>
          <table className="w-full text-sm">
            <tbody>
              {data.most_corrected_fields.map((r) => (
                <tr key={String(r.field_name)} className="border-b border-gray-800/50">
                  <td className="py-2 font-mono text-xs text-gray-300">{r.field_name ?? 'N/A'}</td>
                  <td className="py-2 text-right text-gray-400">{r.count}</td>
                </tr>
              ))}
              {data.most_corrected_fields.length === 0 && (
                <tr><td colSpan={2} className="py-4 text-gray-600 text-center">No field corrections</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h2 className="text-lg font-semibold text-white mb-4">Classification changes</h2>
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
        <h2 className="text-lg font-semibold text-white mb-4">Recent corrections</h2>
        <table className="w-full text-sm">
          <tbody>
            {data.recent_corrections.map((r) => (
              <tr key={r.id} className="border-b border-gray-800/50">
                <td className="py-2 text-gray-500 whitespace-nowrap text-xs">{new Date(r.created_at).toLocaleString()}</td>
                <td className="py-2 text-gray-400">{r.corrected_by_name}</td>
                <td className="py-2 text-gray-400">{r.field_type}</td>
                <td className="py-2">
                  <Link to={`/documents/${r.document_id}`} className="text-blue-400 hover:underline text-xs font-mono truncate max-w-[120px] inline-block align-bottom">
                    {r.document_id.slice(0, 8)}...
                  </Link>
                </td>
                <td className="py-2 text-gray-400 text-xs max-w-md truncate" title={`${r.original_value} -> ${r.corrected_value}`}>
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
  );
}
