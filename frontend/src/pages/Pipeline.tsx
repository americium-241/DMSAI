import { useEffect, useState } from 'react';
import { RefreshCw, Circle, ArrowRight } from 'lucide-react';
import { api, type NodeHealth } from '../api';

const NODE_ORDER = [
  'ingestion', 'conversion', 'storage', 'ocr', 'embedding',
  'entity_extraction', 'classification', 'entity_resolution', 'field_extraction',
];

const NODE_LABELS: Record<string, string> = {
  ingestion: 'Ingestion',
  conversion: 'Conversion',
  storage: 'Storage',
  ocr: 'OCR',
  embedding: 'Embedding',
  entity_extraction: 'Entity Extraction',
  classification: 'Classification',
  entity_resolution: 'Entity Resolution',
  field_extraction: 'Field Extraction',
};

export default function PipelinePage() {
  const [health, setHealth] = useState<Record<string, NodeHealth>>({});
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api.getPipelineHealth().then(setHealth).catch(console.error).finally(() => setLoading(false));
  };

  useEffect(load, []);

  const healthyCount = NODE_ORDER.filter(n => health[n]?.status === 'healthy').length;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Pipeline</h1>
          <p className="text-sm text-gray-500 mt-1">
            {healthyCount}/{NODE_ORDER.length} nodes healthy
          </p>
        </div>
        <button onClick={load} disabled={loading} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gray-800 text-gray-300 text-sm hover:bg-gray-700 transition-colors">
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
                      <span>Pending</span>
                      <span className="text-gray-300">{h.queue.pending}</span>
                    </div>
                    <div className="flex justify-between text-gray-500">
                      <span>Processing</span>
                      <span className="text-gray-300">{h.queue.processing}</span>
                    </div>
                    <div className="flex justify-between text-gray-500">
                      <span>DLQ</span>
                      <span className={h.queue.dead_letter > 0 ? 'text-red-400' : 'text-gray-300'}>{h.queue.dead_letter}</span>
                    </div>
                  </div>
                )}
              </div>
              {i < NODE_ORDER.length - 1 && (
                <ArrowRight size={16} className="text-gray-700 flex-shrink-0" />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
