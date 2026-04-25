import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Plus, Trash2, Search, Archive, ChevronDown, ChevronRight } from 'lucide-react';
import { api, type BucketSummary, type RuleItem } from '../../api';
import Modal from '../../components/Modal';
import { useToast } from '../../components/Toast';

const stateColors: Record<string, string> = {
  open: 'text-green-400', pending: 'text-yellow-400', locked: 'text-red-400', closed: 'text-gray-400',
};

export default function BucketManagement() {
  const { show } = useToast();
  const [buckets, setBuckets] = useState<BucketSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [rules, setRules] = useState<RuleItem[]>([]);

  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');

  const [showRule, setShowRule] = useState(false);
  const [rKind, setRKind] = useState<'standard' | 'llm_vision'>('standard');
  const [rField, setRField] = useState('classification_label');
  const [rOp, setROp] = useState('equals');
  const [rVal, setRVal] = useState('');

  // Low-confidence config
  const [lcEnabled, setLcEnabled] = useState(false);
  const [lcThreshold, setLcThreshold] = useState('0.5');
  const [lcSaving, setLcSaving] = useState(false);

  const load = async () => {
    try {
      const bs = await api.getBuckets();
      setBuckets(bs);
      const configs = await api.getSystemConfig('buckets');
      for (const c of configs) {
        if (c.key === 'low_confidence_bucket_enabled') setLcEnabled(c.value === 'true');
        if (c.key === 'low_confidence_threshold') setLcThreshold(c.value);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const toggleExpand = async (id: string) => {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    const rs = await api.getBucketRules(id);
    setRules(rs);
  };

  const handleCreate = async () => {
    if (!name.trim()) return;
    try {
      await api.createBucket(name, desc || undefined);
      setShowCreate(false);
      setName('');
      setDesc('');
      load();
      show('Bucket created', 'success');
    } catch (e) {
      show(String(e), 'error');
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this bucket and all its documents/rules?')) return;
    await api.deleteBucket(id);
    load();
  };

  const addRule = async () => {
    if (!expandedId || !rVal.trim()) return;
    const field = rKind === 'llm_vision' ? 'llm_vision' : rField;
    const operator = rKind === 'llm_vision' ? rOp : rOp;
    await api.createBucketRule(expandedId, field, operator, rVal);
    setShowRule(false);
    setRKind('standard');
    setRField('classification_label');
    setROp('equals');
    setRVal('');
    const rs = await api.getBucketRules(expandedId);
    setRules(rs);
  };

  const openRuleModal = () => {
    setRKind('standard');
    setRField('classification_label');
    setROp('equals');
    setRVal('');
    setShowRule(true);
  };

  const formatRuleField = (rule: RuleItem) => {
    if (rule.field === 'llm_vision') return 'Vision LLM';
    return rule.field;
  };

  const delRule = async (ruleId: string) => {
    if (!expandedId) return;
    await api.deleteBucketRule(expandedId, ruleId);
    const rs = await api.getBucketRules(expandedId);
    setRules(rs);
  };

  const handleAssign = async () => {
    const r = await api.assignDocuments();
    show(`Assigned ${r.count} documents`, 'success');
    load();
  };

  const saveLcConfig = async () => {
    setLcSaving(true);
    try {
      await api.updateSystemConfig('low_confidence_bucket_enabled', lcEnabled ? 'true' : 'false');
      await api.updateSystemConfig('low_confidence_threshold', lcThreshold);
    } catch (e) {
      console.error(e);
    } finally {
      setLcSaving(false);
    }
  };

  const filtered = filter
    ? buckets.filter(b => b.name.toLowerCase().includes(filter.toLowerCase()))
    : buckets;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Bucket Management</h1>
          <p className="text-sm text-gray-500 mt-1">Create, configure rules, and manage document buckets</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handleAssign} className="px-4 py-2 rounded-lg bg-green-600 text-white text-sm font-medium hover:bg-green-500 transition-colors">
            Run Auto-Assign
          </button>
          <button onClick={() => setShowCreate(true)} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 transition-colors">
            <Plus size={16} /> New Bucket
          </button>
        </div>
      </div>

      <div className="relative w-56">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
        <input
          value={filter} onChange={e => setFilter(e.target.value)}
          className="pl-9 pr-4 py-2 rounded-lg bg-gray-900 border border-gray-800 text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 w-full"
          placeholder="Filter buckets..."
        />
      </div>

      {loading ? (
        <div className="text-gray-500">Loading...</div>
      ) : filtered.length === 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-12 text-center">
          <Archive size={40} className="mx-auto text-gray-700 mb-4" />
          <p className="text-gray-500">{buckets.length === 0 ? 'No buckets yet.' : 'No buckets match.'}</p>
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map(b => (
            <div key={b.id} className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              <div className="flex items-center px-4 py-3 cursor-pointer hover:bg-gray-800/30" onClick={() => toggleExpand(b.id)}>
                {expandedId === b.id ? <ChevronDown size={16} className="text-gray-500 mr-2" /> : <ChevronRight size={16} className="text-gray-500 mr-2" />}
                <span className="text-white font-medium flex-1">{b.name}</span>
                <span className="text-xs text-gray-500 mr-4">{b.description}</span>
                <span className="text-xs text-gray-500 mr-4">{b.total} docs</span>
                {(['open', 'pending', 'locked', 'closed'] as const).map(st => (
                  <span key={st} className={`text-xs font-medium ${stateColors[st]} mx-1.5`}>
                    {b.states[st] || 0} {st}
                  </span>
                ))}
                <Link to={`/admin/buckets/${b.id}`} onClick={e => e.stopPropagation()} className="text-xs text-blue-400 hover:underline ml-3 mr-2">View</Link>
                <button onClick={e => { e.stopPropagation(); handleDelete(b.id); }} className="text-gray-500 hover:text-red-400 ml-1"><Trash2 size={14} /></button>
              </div>

              {expandedId === b.id && (
                <div className="border-t border-gray-800 px-4 py-4">
                  <div className="flex items-center justify-between mb-3">
                    <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Auto-Assignment Rules</h4>
                    <button onClick={openRuleModal} className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"><Plus size={12} /> Add Rule</button>
                  </div>
                  {rules.length === 0 ? (
                    <p className="text-sm text-gray-600">No rules defined</p>
                  ) : (
                    <div className="space-y-2">
                      {rules.map(r => (
                        <div key={r.id} className="flex items-center justify-between bg-gray-800/50 rounded-lg px-3 py-2">
                          <div className="text-sm">
                            <span className="text-blue-400 font-mono">{formatRuleField(r)}</span>
                            <span className="text-gray-500 mx-2">{r.operator}</span>
                            <span className="text-gray-300">"{r.value}"</span>
                          </div>
                          <button onClick={() => delRule(r.id)} className="text-gray-500 hover:text-red-400"><Trash2 size={13} /></button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Low Confidence Bucket Config */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h3 className="text-sm font-semibold text-white uppercase tracking-wider mb-4">Low Confidence Bucket</h3>
        <div className="flex items-center gap-6 flex-wrap">
          <label className="flex items-center gap-2 text-sm text-gray-400">
            <input type="checkbox" checked={lcEnabled} onChange={e => setLcEnabled(e.target.checked)} className="rounded" />
            Enabled
          </label>
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-400">Threshold:</span>
            <input
              type="number" step="0.05" min="0" max="1"
              value={lcThreshold} onChange={e => setLcThreshold(e.target.value)}
              className="w-20 px-2 py-1.5 rounded bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <button onClick={saveLcConfig} disabled={lcSaving} className="px-4 py-1.5 rounded-lg bg-blue-600 text-white text-sm hover:bg-blue-500 disabled:opacity-50 transition-colors">
            {lcSaving ? 'Saving...' : 'Save'}
          </button>
        </div>
        <p className="text-xs text-gray-600 mt-2">Documents with pipeline confidence below this threshold will be auto-assigned to a "Low Confidence" bucket.</p>
      </div>

      {/* Modals */}
      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create Bucket">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Name</label>
            <input value={name} onChange={e => setName(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="e.g. Invoices" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Description</label>
            <input value={desc} onChange={e => setDesc(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="Optional description" />
          </div>
          <button onClick={handleCreate} className="w-full py-2.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 transition-colors">Create Bucket</button>
        </div>
      </Modal>

      <Modal open={showRule} onClose={() => setShowRule(false)} title="Add Rule">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">Rule Type</label>
            <select
              value={rKind}
              onChange={e => {
                const kind = e.target.value as 'standard' | 'llm_vision';
                setRKind(kind);
                setROp(kind === 'llm_vision' ? 'matches' : 'equals');
              }}
              className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="standard">Metadata / extracted field</option>
              <option value="llm_vision">Vision LLM document image rule</option>
            </select>
          </div>
          {rKind === 'standard' ? (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-400 mb-1.5">Field</label>
                <select value={rField} onChange={e => setRField(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  <option value="classification_label">classification_label</option>
                  <option value="classification_subcategory_label">classification_subcategory_label</option>
                  <option value="classification_path">classification_path</option>
                  <option value="mode">mode</option>
                  <option value="status">status</option>
                </select>
                <p className="text-xs text-gray-600 mt-1">Use classification_label for top-level dispatch, classification_subcategory_label for one level below, or classification_path for the full hierarchy.</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-400 mb-1.5">Operator</label>
                <select value={rOp} onChange={e => setROp(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  <option value="equals">equals</option>
                  <option value="contains">contains</option>
                  <option value="in">in (comma-separated)</option>
                </select>
              </div>
            </>
          ) : (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-400 mb-1.5">Operator</label>
                <select value={rOp} onChange={e => setROp(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  <option value="matches">matches</option>
                  <option value="does_not_match">does not match</option>
                </select>
              </div>
              <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
                <p className="text-xs text-amber-200">
                  Vision rules inspect the first page image with the configured vision LLM. Add normal classification or subcategory rules first to keep this targeted, for example: classification_label equals invoice, then Vision LLM matches "the invoice is blue or handwritten".
                </p>
              </div>
            </>
          )}
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">{rKind === 'llm_vision' ? 'Vision Rule' : 'Value'}</label>
            <input
              value={rVal}
              onChange={e => setRVal(e.target.value)}
              className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder={rKind === 'llm_vision' ? 'e.g. the invoice is blue or handwritten' : 'e.g. invoice'}
            />
          </div>
          <button onClick={addRule} className="w-full py-2.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 transition-colors">Add Rule</button>
        </div>
      </Modal>
    </div>
  );
}
