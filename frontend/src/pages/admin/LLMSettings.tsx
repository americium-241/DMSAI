import { type ReactElement, useEffect, useMemo, useState } from 'react';
import { Brain, Plus, RefreshCw, RotateCcw, Save } from 'lucide-react';
import { api, type CanonicalDocumentClassItem, type SystemConfigItem } from '../../api';
import { useToast } from '../../components/Toast';

const LLM_SETTING_KEYS = new Set([
  'llm_provider',
  'ollama_base_url',
  'llm_model',
  'litellm_base_url',
  'litellm_model',
  'llm_temperature',
  'llm_timeout_seconds',
  'llm_vision_timeout_seconds',
  'ocr_vision_model',
  'ocr_vision_prompt',
  'classification_prompt',
  'classification_canonical_map_prompt',
  'entity_extraction_prompt',
  'entity_resolution_prompt',
  'field_detection_prompt',
  'field_extraction_prompt',
  'field_canonical_map_prompt',
  'classification_create_new_categories',
  'classification_new_category_min_confidence',
  'entity_name_match_high',
  'entity_name_match_low',
  'entity_llm_confirm_min',
  // Embedding
  'embedding_enabled',
  'embedding_provider',
  'embedding_model',
]);

const CATEGORY_META: Record<string, { label: string; description: string; order: number }> = {
  llm: { label: 'Provider', description: 'Text and vision LLM provider, model, timeout, and temperature.', order: 0 },
  prompts: { label: 'Prompts', description: 'Prompt templates used by pipeline LLM nodes. Leave placeholders intact.', order: 1 },
  ocr: { label: 'OCR Vision', description: 'Vision model and OCR prompt settings.', order: 2 },
  classification: { label: 'LLM Classification Controls', description: 'Canonical category creation and classification thresholds used by the LLM classifier.', order: 3 },
  entity_resolution: { label: 'Entity Resolution', description: 'Entity matching thresholds and LLM confirmation settings.', order: 4 },
  embedding: { label: 'Embeddings', description: 'Semantic vector embeddings for documents and entities. Uses the same base URL as the chosen provider. Recommended model: nomic-embed-text (Ollama) or text-embedding-3-small (LiteLLM/OpenAI).', order: 5 },
};

const KEY_SERVICES: Record<string, string[]> = {
  llm_provider: ['classification', 'entity_extraction', 'entity_resolution', 'field_extraction', 'ocr'],
  ollama_base_url: ['classification', 'entity_extraction', 'entity_resolution', 'field_extraction', 'ocr'],
  llm_model: ['classification', 'entity_extraction', 'entity_resolution', 'field_extraction', 'ocr'],
  litellm_base_url: ['classification', 'entity_extraction', 'entity_resolution', 'field_extraction', 'ocr'],
  litellm_model: ['classification', 'entity_extraction', 'entity_resolution', 'field_extraction', 'ocr'],
  llm_temperature: ['classification', 'entity_extraction', 'entity_resolution', 'field_extraction', 'ocr'],
  llm_timeout_seconds: ['classification', 'entity_extraction', 'entity_resolution', 'field_extraction'],
  llm_vision_timeout_seconds: ['ocr'],
  ocr_vision_model: ['ocr'],
  ocr_vision_prompt: ['ocr'],
  classification_prompt: ['classification'],
  classification_canonical_map_prompt: ['classification'],
  entity_extraction_prompt: ['entity_extraction'],
  entity_resolution_prompt: ['entity_resolution'],
  field_detection_prompt: ['field_extraction'],
  field_extraction_prompt: ['field_extraction'],
  field_canonical_map_prompt: ['field_extraction'],
  classification_create_new_categories: ['classification'],
  classification_new_category_min_confidence: ['classification'],
  entity_name_match_high: ['entity_resolution'],
  entity_name_match_low: ['entity_resolution'],
  entity_llm_confirm_min: ['entity_resolution'],
  embedding_enabled: ['ocr', 'entity_resolution'],
  embedding_provider: ['ocr', 'entity_resolution'],
  embedding_model: ['ocr', 'entity_resolution'],
};

function isSensitive(key: string) {
  return key.includes('api_key');
}

function isPrompt(item: SystemConfigItem) {
  return item.category === 'prompts' || item.key.includes('prompt');
}

export default function LLMSettingsPage() {
  const { show } = useToast();
  const [configs, setConfigs] = useState<SystemConfigItem[]>([]);
  const [classes, setClasses] = useState<CanonicalDocumentClassItem[]>([]);
  const [editing, setEditing] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [dirtyServices, setDirtyServices] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [restarting, setRestarting] = useState(false);
  const [classParentId, setClassParentId] = useState('');
  const [className, setClassName] = useState('');
  const [classDesc, setClassDesc] = useState('');
  const [classAliases, setClassAliases] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const [items, classItems] = await Promise.all([
        api.getSystemConfig(),
        api.getCanonicalDocumentClasses().catch(() => [] as CanonicalDocumentClassItem[]),
      ]);
      const filtered = items.filter((item) => LLM_SETTING_KEYS.has(item.key));
      setConfigs(filtered);
      setClasses(classItems);
      setEditing(Object.fromEntries(filtered.map((item) => [item.key, item.value])));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const groups = useMemo(() => {
    const byCategory: Record<string, SystemConfigItem[]> = {};
    for (const item of configs) {
      if (!byCategory[item.category]) byCategory[item.category] = [];
      byCategory[item.category].push(item);
    }
    return Object.entries(byCategory)
      .map(([category, items]) => ({ category, items, meta: CATEGORY_META[category] || { label: category, description: '', order: 99 } }))
      .sort((a, b) => a.meta.order - b.meta.order);
  }, [configs]);

  const saveKey = async (key: string) => {
    setSaving((prev) => ({ ...prev, [key]: true }));
    try {
      await api.updateSystemConfig(key, editing[key] ?? '');
      setDirtyServices((prev) => new Set([...prev, ...(KEY_SERVICES[key] || [])]));
      show(`Saved ${key}`, 'success');
      await load();
    } catch (e) {
      show(String(e), 'error');
    } finally {
      setSaving((prev) => ({ ...prev, [key]: false }));
    }
  };

  const restartDirtyServices = async () => {
    const services = [...dirtyServices];
    if (!services.length) return;
    setRestarting(true);
    try {
      await api.restartServices(services);
      setDirtyServices(new Set());
      show(`Restart started: ${services.join(', ')}`, 'success');
    } catch (e) {
      show(String(e), 'error');
    } finally {
      setRestarting(false);
    }
  };

  const addClass = async () => {
    if (!className.trim()) return;
    try {
      await api.createCanonicalDocumentClass({
        canonical_name: className.trim(),
        description: classDesc.trim(),
        parent_id: classParentId || null,
        aliases: classAliases.split(',').map((a) => a.trim()).filter(Boolean),
      });
      setClassName('');
      setClassDesc('');
      setClassAliases('');
      setClassParentId('');
      setClasses(await api.getCanonicalDocumentClasses());
      setDirtyServices((prev) => new Set([...prev, 'classification']));
      show('Canonical class added', 'success');
    } catch (e) {
      show(String(e), 'error');
    }
  };

  const childrenByParent: Record<string, CanonicalDocumentClassItem[]> = {};
  for (const cls of classes) {
    const key = cls.parent_id || 'root';
    if (!childrenByParent[key]) childrenByParent[key] = [];
    childrenByParent[key].push(cls);
  }
  const renderClassRows = (parentId: string | null = null, depth = 0): ReactElement[] => {
    const rows = [...(childrenByParent[parentId || 'root'] || [])].sort((a, b) => a.canonical_name.localeCompare(b.canonical_name));
    return rows.flatMap((cls): ReactElement[] => [
      <div key={cls.id} className="flex items-start justify-between rounded-lg bg-gray-800/50 px-3 py-2">
        <div style={{ paddingLeft: `${depth * 18}px` }}>
          <div className="text-sm text-gray-200 font-medium">{cls.canonical_name}</div>
          <div className="text-xs text-gray-500">{cls.description || 'No description'}</div>
          {cls.aliases.length > 0 && <div className="text-xs text-gray-600">Aliases: {cls.aliases.join(', ')}</div>}
        </div>
        <div className="text-xs text-gray-600">{depth === 0 ? 'category' : `level ${depth + 1}`}</div>
      </div>,
      ...renderClassRows(cls.id, depth + 1),
    ]);
  };

  if (loading) return <div className="text-gray-500">Loading LLM settings...</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">LLM Settings</h1>
          <p className="text-sm text-gray-500 mt-1">Configure providers, prompts, AI thresholds, and restart affected nodes.</p>
        </div>
        <button onClick={load} className="text-gray-500 hover:text-gray-300"><RefreshCw size={16} /></button>
      </div>

      {dirtyServices.size > 0 && (
        <div className="flex items-center justify-between rounded-xl border border-amber-700/40 bg-amber-950/20 p-4">
          <div>
            <div className="text-sm font-medium text-amber-300">Restart recommended</div>
            <div className="text-xs text-amber-500">Affected services: {[...dirtyServices].join(', ')}</div>
          </div>
          <button onClick={restartDirtyServices} disabled={restarting}
            className="flex items-center gap-2 rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-500 disabled:opacity-50">
            <RotateCcw size={15} /> {restarting ? 'Restarting...' : 'Restart Affected Nodes'}
          </button>
        </div>
      )}

      <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
        <div className="mb-4 flex items-center gap-2">
          <Brain size={18} className="text-blue-400" />
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wider text-white">Canonical Classification Hierarchy</h3>
            <p className="text-xs text-gray-500">Create categories and subcategories for LLM classification and bucket routing.</p>
          </div>
        </div>
        <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-4">
          <select value={classParentId} onChange={(e) => setClassParentId(e.target.value)}
            className="rounded-lg border border-gray-700 bg-gray-800 px-3.5 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">Top-level category</option>
            {classes.map((cls) => <option key={cls.id} value={cls.id}>{cls.parent_id ? '-- ' : ''}{cls.canonical_name}</option>)}
          </select>
          <input value={className} onChange={(e) => setClassName(e.target.value)}
            className="rounded-lg border border-gray-700 bg-gray-800 px-3.5 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="canonical_name" />
          <input value={classDesc} onChange={(e) => setClassDesc(e.target.value)}
            className="rounded-lg border border-gray-700 bg-gray-800 px-3.5 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Description" />
          <div className="flex gap-2">
            <input value={classAliases} onChange={(e) => setClassAliases(e.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-gray-700 bg-gray-800 px-3.5 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="aliases, comma-separated" />
            <button onClick={addClass}
              className="flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-2 text-sm text-white transition-colors hover:bg-blue-500">
              <Plus size={14} /> Add
            </button>
          </div>
        </div>
        <div className="space-y-2">{renderClassRows()}</div>
      </div>

      {groups.map(({ category, items, meta }) => (
        <div key={category} className="rounded-xl border border-gray-800 bg-gray-900 p-5">
          <h3 className="mb-1 text-sm font-semibold uppercase tracking-wider text-white">{meta.label}</h3>
          <p className="mb-4 text-xs text-gray-500">{meta.description}</p>
          <div className="space-y-4">
            {items.map((item) => {
              const changed = editing[item.key] !== item.value;
              const isSaving = saving[item.key];
              const toggle = editing[item.key] === 'true' || editing[item.key] === 'false';
              return (
                <div key={item.key}>
                  <div className="mb-1.5 flex items-center justify-between">
                    <div>
                      <label className="text-sm text-gray-300">{item.description || item.key}</label>
                      <span className="ml-2 font-mono text-xs text-gray-600">{item.key}</span>
                    </div>
                    {changed && (
                      <button onClick={() => saveKey(item.key)} disabled={isSaving}
                        className="flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-500 disabled:opacity-50">
                        <Save size={12} /> {isSaving ? 'Saving...' : 'Save'}
                      </button>
                    )}
                  </div>
                  {toggle ? (
                    <button onClick={() => setEditing((prev) => ({ ...prev, [item.key]: prev[item.key] === 'true' ? 'false' : 'true' }))}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${editing[item.key] === 'true' ? 'bg-blue-600' : 'bg-gray-700'}`}>
                      <span className={`inline-block h-4 w-4 rounded-full bg-white transition-transform ${editing[item.key] === 'true' ? 'translate-x-6' : 'translate-x-1'}`} />
                    </button>
                  ) : isPrompt(item) ? (
                    <textarea rows={8} value={editing[item.key] || ''} onChange={(e) => setEditing((prev) => ({ ...prev, [item.key]: e.target.value }))}
                      className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3.5 py-2 font-mono text-xs text-white focus:outline-none focus:ring-2 focus:ring-blue-500" />
                  ) : (
                    <input type={isSensitive(item.key) ? 'password' : 'text'} value={editing[item.key] || ''} onChange={(e) => setEditing((prev) => ({ ...prev, [item.key]: e.target.value }))}
                      className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3.5 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500" />
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
