import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FileText, Building2, ChevronRight, Brain, Folder,
  Mail, CheckCircle2, ArrowRight, Loader2, Wifi, WifiOff, SkipForward,
  Upload, LayoutDashboard, Settings,
} from 'lucide-react';
import { api } from '../api';
import { useAuth } from '../auth';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
type LLMProvider = 'ollama' | 'gemini' | 'openai' | 'anthropic' | 'other';
type IngestionType = 'directory' | 'email' | 'skip';

interface StepState {
  // Step 1 — Account
  orgName: string;
  fullName: string;
  email: string;
  password: string;
  confirmPassword: string;

  // Step 2 — LLM
  llmProvider: LLMProvider;
  // Ollama
  ollamaUrl: string;
  ollamaModel: string;
  // Cloud providers (Gemini, OpenAI, Anthropic)
  cloudApiKey: string;
  cloudTextModel: string;
  // Advanced (other)
  litellmUrl: string;
  litellmApiKey: string;
  litellmModel: string;
  // Embedding (optional)
  embeddingEnabled: boolean;
  embeddingModel: string;

  // Step 3 — Ingestion
  ingestionType: IngestionType;
  directoryPath: string;
  imapHost: string;
  imapPort: string;
  imapUser: string;
  imapPassword: string;
  imapFolder: string;
}

// ---------------------------------------------------------------------------
// Model catalogues
// ---------------------------------------------------------------------------
const CLOUD_PROVIDERS: {
  id: LLMProvider;
  label: string;
  desc: string;
  apiKeyLabel: string;
  apiKeyUrl: string;
  textModels: { id: string; label: string }[];
  defaultEmbedding: string;
  embedModels: { id: string; label: string }[];
}[] = [
  {
    id: 'gemini',
    label: 'Google Gemini',
    desc: 'Fast multimodal models — handles OCR, text & embeddings',
    apiKeyLabel: 'aistudio.google.com',
    apiKeyUrl: 'https://aistudio.google.com/app/apikey',
    textModels: [
      { id: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash  ✦ Recommended' },
      { id: 'gemini-2.0-flash-lite', label: 'Gemini 2.0 Flash Lite  ✦ Cheapest' },
      { id: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash  ✦ Latest' },
      { id: 'gemini-1.5-pro', label: 'Gemini 1.5 Pro  ✦ Most capable' },
    ],
    defaultEmbedding: 'gemini-embedding-001',
    embedModels: [
      { id: 'gemini-embedding-001', label: 'Gemini Embedding 001' },
    ],
  },
  {
    id: 'openai',
    label: 'OpenAI',
    desc: 'GPT-4o and GPT-4.1 family — best-in-class reasoning',
    apiKeyLabel: 'platform.openai.com',
    apiKeyUrl: 'https://platform.openai.com/api-keys',
    textModels: [
      { id: 'gpt-4o-mini', label: 'GPT-4o Mini  ✦ Recommended' },
      { id: 'gpt-4o', label: 'GPT-4o  ✦ Best quality' },
      { id: 'gpt-4.1-mini', label: 'GPT-4.1 Mini  ✦ Latest mini' },
      { id: 'gpt-4.1', label: 'GPT-4.1  ✦ Latest best' },
    ],
    defaultEmbedding: 'text-embedding-3-small',
    embedModels: [
      { id: 'text-embedding-3-small', label: 'text-embedding-3-small  ✦ Recommended' },
      { id: 'text-embedding-3-large', label: 'text-embedding-3-large  ✦ Best quality' },
    ],
  },
  {
    id: 'anthropic',
    label: 'Anthropic Claude',
    desc: 'Claude 3.5 / 3.7 — excellent for document analysis',
    apiKeyLabel: 'console.anthropic.com',
    apiKeyUrl: 'https://console.anthropic.com/settings/keys',
    textModels: [
      { id: 'claude-3-5-haiku-20241022', label: 'Claude 3.5 Haiku  ✦ Recommended (fast)' },
      { id: 'claude-3-5-sonnet-20241022', label: 'Claude 3.5 Sonnet  ✦ Best quality' },
      { id: 'claude-3-7-sonnet-20250219', label: 'Claude 3.7 Sonnet  ✦ Latest' },
    ],
    defaultEmbedding: '',
    embedModels: [],
  },
];

const OLLAMA_TEXT_MODELS = [
  { id: 'gemma3:27b', label: 'gemma3:27b  ✦ Recommended (multimodal, 27B)' },
  { id: 'gemma3:12b', label: 'gemma3:12b  ✦ Lighter (multimodal, 12B)' },
  { id: 'gemma3:4b', label: 'gemma3:4b  ✦ Very fast (multimodal, 4B)' },
  { id: 'llama3.2:3b', label: 'llama3.2:3b  ✦ Tiny (text only)' },
  { id: 'qwen2.5:7b', label: 'qwen2.5:7b  ✦ Good alternative' },
  { id: 'mistral:7b', label: 'mistral:7b  ✦ Classic' },
];

const OLLAMA_EMBED_MODELS = [
  { id: 'nomic-embed-text', label: 'nomic-embed-text  ✦ Recommended' },
  { id: 'mxbai-embed-large', label: 'mxbai-embed-large  ✦ Higher quality' },
  { id: 'all-minilm', label: 'all-minilm  ✦ Very fast, small' },
];

const INITIAL: StepState = {
  orgName: '', fullName: '', email: '', password: '', confirmPassword: '',
  llmProvider: 'ollama',
  ollamaUrl: 'http://localhost:11434', ollamaModel: 'gemma3:27b',
  cloudApiKey: '', cloudTextModel: '',
  litellmUrl: 'http://localhost:4000', litellmApiKey: '', litellmModel: '',
  embeddingEnabled: false, embeddingModel: '',
  ingestionType: 'skip',
  directoryPath: '', imapHost: '', imapPort: '993',
  imapUser: '', imapPassword: '', imapFolder: 'INBOX',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function cls(...parts: (string | false | undefined)[]) {
  return parts.filter(Boolean).join(' ');
}

function Label({ children }: { children: React.ReactNode }) {
  return <label className="block text-sm font-medium text-gray-400 mb-1.5">{children}</label>;
}

function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
    />
  );
}

function ErrorBox({ msg }: { msg: string }) {
  return (
    <div className="px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
      {msg}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step indicator
// ---------------------------------------------------------------------------
const STEPS = ['Account', 'LLM', 'Ingestion', 'Ready'];

function StepBar({ current }: { current: number }) {
  return (
    <div className="flex items-center justify-center gap-0 mb-8 select-none">
      {STEPS.map((label, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <div key={i} className="flex items-center">
            <div className="flex flex-col items-center">
              <div className={cls(
                'w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold transition-all',
                done && 'bg-blue-600 text-white',
                active && 'bg-blue-500 text-white ring-2 ring-blue-400 ring-offset-2 ring-offset-gray-950',
                !done && !active && 'bg-gray-800 text-gray-500 border border-gray-700',
              )}>
                {done ? <CheckCircle2 size={16} /> : i + 1}
              </div>
              <span className={cls(
                'text-xs mt-1 font-medium',
                active ? 'text-blue-400' : done ? 'text-gray-400' : 'text-gray-600',
              )}>
                {label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <div className={cls(
                'w-12 h-0.5 mb-5 mx-1 transition-colors',
                i < current ? 'bg-blue-600' : 'bg-gray-700',
              )} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 1 — Account & Organisation
// ---------------------------------------------------------------------------
function Step1({
  state, setState, onNext,
}: {
  state: StepState;
  setState: (s: StepState) => void;
  onNext: () => void;
}) {
  const { register } = useAuth();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const set = (k: keyof StepState) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setState({ ...state, [k]: e.target.value });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (state.password !== state.confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    if (state.password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    setLoading(true);
    try {
      const result = await register(state.email, state.password, state.fullName, state.orgName || undefined);
      if (result.verification_required) {
        setError('Email verification is required. Please disable it in General Settings first, or verify your email and return.');
        return;
      }
      onNext();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Registration failed';
      try { setError(JSON.parse(msg).detail || msg); } catch { setError(msg); }
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="col-span-2">
          <Label>Organisation Name</Label>
          <Input
            type="text" value={state.orgName} onChange={set('orgName')}
            placeholder="Acme Corp" required
          />
        </div>
        <div className="col-span-2">
          <Label>Your Full Name</Label>
          <Input
            type="text" value={state.fullName} onChange={set('fullName')}
            placeholder="Jane Doe" required
          />
        </div>
        <div className="col-span-2">
          <Label>Admin Email</Label>
          <Input
            type="email" value={state.email} onChange={set('email')}
            placeholder="admin@example.com" required
          />
        </div>
        <div>
          <Label>Password</Label>
          <Input
            type="password" value={state.password} onChange={set('password')}
            placeholder="Min 8 characters" required
          />
        </div>
        <div>
          <Label>Confirm Password</Label>
          <Input
            type="password" value={state.confirmPassword} onChange={set('confirmPassword')}
            placeholder="Repeat password" required
          />
        </div>
      </div>
      <p className="text-xs text-gray-500">
        Min. 8 characters, one uppercase letter, one digit.
      </p>

      {error && <ErrorBox msg={error} />}

      <button
        type="submit" disabled={loading}
        className="w-full py-2.5 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-500 disabled:opacity-50 transition-colors flex items-center justify-center gap-2"
      >
        {loading ? <Loader2 size={16} className="animate-spin" /> : null}
        {loading ? 'Creating account…' : 'Create Account & Continue'}
        {!loading && <ChevronRight size={16} />}
      </button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Step 2 — LLM Configuration
// ---------------------------------------------------------------------------
type TestResult = 'idle' | 'testing' | 'ok' | 'fail';

// ---------------------------------------------------------------------------
// Shared sub-components for Step 2
// ---------------------------------------------------------------------------
function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        onClick={() => onChange(!on)}
        className={cls('relative w-10 h-5 rounded-full transition-colors shrink-0',
          on ? 'bg-blue-600' : 'bg-gray-700')}
      >
        <span className={cls('absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform',
          on ? 'translate-x-5' : 'translate-x-0.5')} />
      </button>
      <span className="text-sm text-gray-400">{label}</span>
    </div>
  );
}

function ModelSelect({
  label, value, onChange, options, placeholder,
}: {
  label: React.ReactNode;
  value: string;
  onChange: (v: string) => void;
  options: { id: string; label: string }[];
  placeholder?: string;
}) {
  const isCustom = value !== '' && !options.find(o => o.id === value);
  const [custom, setCustom] = useState(isCustom ? value : '');
  const [showCustom, setShowCustom] = useState(isCustom);

  const handleSelect = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const v = e.target.value;
    if (v === '__custom__') { setShowCustom(true); return; }
    setShowCustom(false);
    onChange(v);
  };

  const selectValue = showCustom ? '__custom__' : (value || '');

  return (
    <div>
      <Label>{label}</Label>
      <select
        value={selectValue}
        onChange={handleSelect}
        className="w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      >
        {placeholder && <option value="" disabled>{placeholder}</option>}
        {options.map(o => (
          <option key={o.id} value={o.id}>{o.label}</option>
        ))}
        <option value="__custom__">Custom model name…</option>
      </select>
      {showCustom && (
        <input
          type="text"
          value={custom}
          onChange={e => { setCustom(e.target.value); onChange(e.target.value); }}
          placeholder="Enter model name"
          className="mt-2 w-full px-3.5 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
          autoFocus
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 2 — LLM Configuration
// ---------------------------------------------------------------------------
function Step2({
  state, setState, onNext, onBack,
}: {
  state: StepState;
  setState: (s: StepState) => void;
  onNext: () => void;
  onBack: () => void;
}) {
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState<TestResult>('idle');

  const cloudDef = CLOUD_PROVIDERS.find(p => p.id === state.llmProvider);

  // Auto-set default model when switching provider
  const selectProvider = (p: LLMProvider) => {
    const def = CLOUD_PROVIDERS.find(x => x.id === p);
    setState({
      ...state,
      llmProvider: p,
      cloudTextModel: def ? def.textModels[0].id : '',
      embeddingModel: def ? def.defaultEmbedding : (p === 'ollama' ? 'nomic-embed-text' : ''),
    });
  };

  const buildPayload = () => {
    const p = state.llmProvider;
    if (p === 'ollama') {
      return {
        provider: 'ollama',
        text_model: state.ollamaModel,
        ollama_url: state.ollamaUrl,
        embedding_enabled: state.embeddingEnabled,
        embedding_model: state.embeddingEnabled ? state.embeddingModel : '',
      };
    }
    if (p === 'other') {
      return {
        provider: 'other',
        text_model: state.litellmModel,
        api_key: state.litellmApiKey,
        ollama_url: state.litellmUrl,
        embedding_enabled: state.embeddingEnabled,
        embedding_model: state.embeddingEnabled ? state.embeddingModel : '',
      };
    }
    // Cloud providers (gemini, openai, anthropic)
    return {
      provider: p,
      text_model: state.cloudTextModel,
      api_key: state.cloudApiKey,
      embedding_enabled: state.embeddingEnabled,
      embedding_model: state.embeddingEnabled ? state.embeddingModel : '',
    };
  };

  const handleApply = async () => {
    setError('');
    setSaving(true);
    try {
      if (state.llmProvider !== 'ollama' && state.llmProvider !== 'other' && !state.cloudApiKey.trim()) {
        throw new Error('API key is required for cloud providers.');
      }
      if (!state.cloudTextModel && state.llmProvider !== 'ollama' && state.llmProvider !== 'other') {
        throw new Error('Please select a model.');
      }
      await api.applyLLMConfig(buildPayload());
      onNext();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to save LLM settings';
      try { setError(JSON.parse(msg).detail || msg); } catch { setError(msg); }
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTestResult('testing');
    try {
      await api.applyLLMConfig(buildPayload());
      const health = await api.getPipelineHealth();
      const up = Object.values(health).some((n: any) => n.status === 'ok' || n.status === 'healthy');
      setTestResult(up ? 'ok' : 'fail');
    } catch {
      setTestResult('fail');
    }
  };

  const PROVIDER_CARDS: { id: LLMProvider; label: string; sublabel: string }[] = [
    { id: 'ollama', label: 'Ollama', sublabel: 'Run locally, no API key' },
    { id: 'gemini', label: 'Gemini', sublabel: 'Google AI — free tier available' },
    { id: 'openai', label: 'OpenAI', sublabel: 'GPT-4o family' },
    { id: 'anthropic', label: 'Claude', sublabel: 'Anthropic — great for docs' },
    { id: 'other', label: 'Other', sublabel: 'LiteLLM proxy (advanced)' },
  ];

  return (
    <div className="space-y-5">
      {/* Provider selector */}
      <div>
        <Label>Choose your AI provider</Label>
        <div className="grid grid-cols-5 gap-2">
          {PROVIDER_CARDS.map(({ id, label, sublabel }) => (
            <button
              key={id}
              type="button"
              onClick={() => selectProvider(id)}
              className={cls(
                'flex flex-col items-center gap-1 px-2 py-3 rounded-lg border text-center transition-all',
                state.llmProvider === id
                  ? 'bg-blue-600/20 border-blue-500 text-blue-300'
                  : 'bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-600',
              )}
            >
              <span className="text-sm font-semibold">{label}</span>
              <span className="text-xs text-gray-500 leading-tight">{sublabel}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Ollama */}
      {state.llmProvider === 'ollama' && (
        <>
          <div>
            <Label>Ollama URL</Label>
            <Input
              type="url"
              value={state.ollamaUrl}
              onChange={e => setState({ ...state, ollamaUrl: e.target.value })}
              placeholder="http://localhost:11434"
            />
          </div>
          <ModelSelect
            label="Model"
            value={state.ollamaModel}
            onChange={v => setState({ ...state, ollamaModel: v })}
            options={OLLAMA_TEXT_MODELS}
            placeholder="Select a model…"
          />
          <p className="text-xs text-gray-500 -mt-3">
            Run <code className="bg-gray-800 px-1 rounded">ollama pull {state.ollamaModel || 'gemma3:27b'}</code> first if you haven't already.
            Multimodal models (gemma3, llava…) also handle OCR — no separate vision model needed.
          </p>
        </>
      )}

      {/* Cloud providers */}
      {cloudDef && (
        <>
          <div>
            <Label>
              API Key —{' '}
              <a href={cloudDef.apiKeyUrl} target="_blank" rel="noopener noreferrer"
                className="text-blue-400 hover:text-blue-300 underline">
                Get one at {cloudDef.apiKeyLabel}
              </a>
            </Label>
            <Input
              type="password"
              value={state.cloudApiKey}
              onChange={e => setState({ ...state, cloudApiKey: e.target.value })}
              placeholder="Paste your API key here"
            />
          </div>
          <ModelSelect
            label="Model"
            value={state.cloudTextModel || cloudDef.textModels[0].id}
            onChange={v => setState({ ...state, cloudTextModel: v })}
            options={cloudDef.textModels}
          />
          <p className="text-xs text-gray-500 -mt-3">
            This model handles OCR, entity extraction, classification and field extraction.
            Cloud models are multimodal — no separate vision model is needed.
          </p>
        </>
      )}

      {/* Advanced / Other */}
      {state.llmProvider === 'other' && (
        <>
          <div className="px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-xs text-gray-400">
            Advanced: connect to a custom LiteLLM proxy. The proxy must be running and configured with your provider API keys.
          </div>
          <div>
            <Label>Proxy URL</Label>
            <Input type="url" value={state.litellmUrl}
              onChange={e => setState({ ...state, litellmUrl: e.target.value })}
              placeholder="http://localhost:4000" />
          </div>
          <div>
            <Label>API Key (optional)</Label>
            <Input type="password" value={state.litellmApiKey}
              onChange={e => setState({ ...state, litellmApiKey: e.target.value })}
              placeholder="sk-… or leave empty" />
          </div>
          <div>
            <Label>Model</Label>
            <Input type="text" value={state.litellmModel}
              onChange={e => setState({ ...state, litellmModel: e.target.value })}
              placeholder="gemini/gemini-2.0-flash or openai/gpt-4o" />
          </div>
        </>
      )}

      {/* Embedding — optional, collapsed */}
      <details className="group">
        <summary className="cursor-pointer text-sm text-gray-400 hover:text-gray-300 select-none list-none flex items-center gap-2 py-1">
          <span className="text-gray-600 group-open:rotate-90 transition-transform inline-block">▶</span>
          Embedding <span className="text-gray-600 text-xs">(optional — improves entity matching accuracy)</span>
        </summary>
        <div className="mt-3 space-y-3 pl-3 border-l border-gray-700">
          <Toggle
            on={state.embeddingEnabled}
            onChange={v => setState({ ...state, embeddingEnabled: v })}
            label="Enable embedding-based entity pre-filtering"
          />
          {state.embeddingEnabled && (
            <>
              {state.llmProvider === 'ollama' && (
                <ModelSelect
                  label="Embedding Model"
                  value={state.embeddingModel || 'nomic-embed-text'}
                  onChange={v => setState({ ...state, embeddingModel: v })}
                  options={OLLAMA_EMBED_MODELS}
                />
              )}
              {cloudDef && cloudDef.embedModels.length > 0 && (
                <ModelSelect
                  label="Embedding Model"
                  value={state.embeddingModel || cloudDef.defaultEmbedding}
                  onChange={v => setState({ ...state, embeddingModel: v })}
                  options={cloudDef.embedModels}
                />
              )}
              {cloudDef && cloudDef.embedModels.length === 0 && (
                <p className="text-xs text-yellow-400">
                  Anthropic does not provide embedding models. Use a different provider for embeddings, or disable.
                </p>
              )}
              {state.llmProvider === 'ollama' && (
                <p className="text-xs text-gray-500">
                  Run <code className="bg-gray-800 px-1 rounded">ollama pull {state.embeddingModel || 'nomic-embed-text'}</code> first.
                </p>
              )}
            </>
          )}
        </div>
      </details>

      {/* Test connection */}
      <div className="flex items-center gap-3 pt-1">
        <button
          type="button"
          onClick={handleTest}
          disabled={testResult === 'testing' || saving}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-300 hover:border-gray-600 disabled:opacity-50 transition-colors"
        >
          {testResult === 'testing' ? <Loader2 size={14} className="animate-spin" /> : <Wifi size={14} />}
          Test Connection
        </button>
        {testResult === 'ok' && <span className="flex items-center gap-1 text-green-400 text-sm"><CheckCircle2 size={14} /> Connected</span>}
        {testResult === 'fail' && <span className="flex items-center gap-1 text-yellow-400 text-sm"><WifiOff size={14} /> Could not connect — you can still continue</span>}
      </div>

      {error && <ErrorBox msg={error} />}

      <div className="flex gap-3">
        <button type="button" onClick={onBack}
          className="px-4 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-300 hover:bg-gray-700 transition-colors">
          Back
        </button>
        <button type="button" onClick={handleApply} disabled={saving}
          className="flex-1 py-2.5 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-500 disabled:opacity-50 transition-colors flex items-center justify-center gap-2">
          {saving && <Loader2 size={16} className="animate-spin" />}
          {saving ? 'Applying…' : 'Apply & Continue'}
          {!saving && <ChevronRight size={16} />}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 3 — Ingestion Source
// ---------------------------------------------------------------------------
function Step3({
  state, setState, onNext, onBack,
}: {
  state: StepState;
  setState: (s: StepState) => void;
  onNext: () => void;
  onBack: () => void;
}) {
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const set = (k: keyof StepState) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setState({ ...state, [k]: e.target.value });

  const TYPE_CARDS: { type: IngestionType; icon: React.ElementType; title: string; desc: string }[] = [
    { type: 'directory', icon: Folder, title: 'Watch a Directory', desc: 'Automatically ingest documents dropped into a folder' },
    { type: 'email', icon: Mail, title: 'Email Inbox (IMAP)', desc: 'Pull attachments from an IMAP mailbox' },
    { type: 'skip', icon: SkipForward, title: 'Skip for Now', desc: 'Configure ingestion sources later via Organizations' },
  ];

  const handleNext = async () => {
    if (state.ingestionType === 'skip') { onNext(); return; }

    setError('');
    setSaving(true);
    try {
      const org = await api.getOrganization();
      let config: Record<string, string> = {};

      if (state.ingestionType === 'directory') {
        if (!state.directoryPath.trim()) {
          setError('Please enter a directory path.');
          setSaving(false);
          return;
        }
        config = { watch_directory: state.directoryPath.trim() };
      } else {
        if (!state.imapHost.trim() || !state.imapUser.trim()) {
          setError('Please fill in IMAP host and username.');
          setSaving(false);
          return;
        }
        config = {
          imap_host: state.imapHost,
          imap_port: state.imapPort,
          imap_user: state.imapUser,
          imap_password: state.imapPassword,
          imap_folder: state.imapFolder,
        };
      }

      await api.adminCreateIngestionConfig(org.id, {
        name: state.ingestionType === 'directory' ? 'Document Watcher' : 'Email Inbox',
        source_type: state.ingestionType,
        config,
        is_active: true,
      });
      onNext();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to save ingestion config';
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-3">
        {TYPE_CARDS.map(({ type, icon: Icon, title, desc }) => (
          <button
            key={type}
            type="button"
            onClick={() => setState({ ...state, ingestionType: type })}
            className={cls(
              'flex items-start gap-3 px-4 py-3 rounded-lg border text-left transition-all',
              state.ingestionType === type
                ? 'bg-blue-600/15 border-blue-500 text-blue-300'
                : 'bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-600',
            )}
          >
            <Icon size={18} className="mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-semibold">{title}</p>
              <p className="text-xs text-gray-500 mt-0.5">{desc}</p>
            </div>
          </button>
        ))}
      </div>

      {state.ingestionType === 'directory' && (
        <div>
          <Label>Directory Path</Label>
          <Input
            type="text" value={state.directoryPath} onChange={set('directoryPath')}
            placeholder="/home/user/documents  or  C:\Users\user\Documents"
          />
          <p className="mt-1 text-xs text-gray-500">Absolute path on the machine running DMSAI.</p>
        </div>
      )}

      {state.ingestionType === 'email' && (
        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <Label>IMAP Host</Label>
              <Input type="text" value={state.imapHost} onChange={set('imapHost')} placeholder="imap.example.com" />
            </div>
            <div>
              <Label>Port</Label>
              <Input type="number" value={state.imapPort} onChange={set('imapPort')} placeholder="993" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Username</Label>
              <Input type="text" value={state.imapUser} onChange={set('imapUser')} placeholder="user@example.com" />
            </div>
            <div>
              <Label>Password</Label>
              <Input type="password" value={state.imapPassword} onChange={set('imapPassword')} placeholder="••••••" />
            </div>
          </div>
          <div>
            <Label>Folder</Label>
            <Input type="text" value={state.imapFolder} onChange={set('imapFolder')} placeholder="INBOX" />
          </div>
        </div>
      )}

      {error && <ErrorBox msg={error} />}

      <div className="flex gap-3 pt-1">
        <button
          type="button" onClick={onBack}
          className="px-4 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-300 hover:bg-gray-700 transition-colors"
        >
          Back
        </button>
        <button
          type="button" onClick={handleNext} disabled={saving}
          className="flex-1 py-2.5 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-500 disabled:opacity-50 transition-colors flex items-center justify-center gap-2"
        >
          {saving ? <Loader2 size={16} className="animate-spin" /> : null}
          {saving ? 'Saving…' : state.ingestionType === 'skip' ? 'Skip & Continue' : 'Save & Continue'}
          {!saving && <ChevronRight size={16} />}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 4 — Ready
// ---------------------------------------------------------------------------
function Step4() {
  const [done, setDone] = useState(false);

  useEffect(() => {
    api.updateSystemConfig('setup_completed', 'true').catch(() => {}).finally(() => setDone(true));
  }, []);

  const ACTIONS = [
    {
      icon: Upload, label: 'Upload Your First Document', desc: 'Drop a file and watch the pipeline process it',
      to: '/upload', color: 'blue',
    },
    {
      icon: LayoutDashboard, label: 'Go to Dashboard', desc: 'See an overview of your documents and activity',
      to: '/', color: 'gray',
    },
    {
      icon: Settings, label: 'Review LLM Settings', desc: 'Fine-tune prompts, thresholds, and model configuration',
      to: '/admin/llm-settings', color: 'gray',
    },
  ];

  return (
    <div className="space-y-6">
      <div className="text-center py-2">
        <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-green-500/20 mb-3">
          <CheckCircle2 size={28} className="text-green-400" />
        </div>
        <h3 className="text-lg font-semibold text-white">DMSAI is ready!</h3>
        <p className="text-sm text-gray-400 mt-1">Your organisation and admin account have been created.</p>
      </div>

      <div className="space-y-3">
        {ACTIONS.map(({ icon: Icon, label, desc, to, color }) => (
          <button
            key={to}
            type="button"
            disabled={!done}
            onClick={() => { if (done) { window.location.href = to; } }}
            className={cls(
              'w-full flex items-center gap-4 px-4 py-3.5 rounded-lg border text-left transition-all disabled:opacity-40',
              color === 'blue'
                ? 'bg-blue-600/20 border-blue-500/50 hover:bg-blue-600/30'
                : 'bg-gray-800 border-gray-700 hover:border-gray-600',
            )}
          >
            <div className={cls(
              'w-9 h-9 rounded-lg flex items-center justify-center shrink-0',
              color === 'blue' ? 'bg-blue-600/40' : 'bg-gray-700',
            )}>
              <Icon size={18} className={color === 'blue' ? 'text-blue-300' : 'text-gray-300'} />
            </div>
            <div className="flex-1">
              <p className="text-sm font-semibold text-white">{label}</p>
              <p className="text-xs text-gray-500 mt-0.5">{desc}</p>
            </div>
            <ArrowRight size={16} className="text-gray-500 shrink-0" />
          </button>
        ))}
      </div>

      {!done && (
        <p className="text-center text-xs text-gray-500 flex items-center justify-center gap-1">
          <Loader2 size={12} className="animate-spin" /> Finalising setup…
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Setup page
// ---------------------------------------------------------------------------
export default function SetupPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [state, setState] = useState<StepState>(INITIAL);
  const [checking, setChecking] = useState(true);

  // If setup is already complete, redirect to the main app
  useEffect(() => {
    api.getSetupStatus().then(s => {
      if (s.completed) navigate('/', { replace: true });
    }).catch(() => {}).finally(() => setChecking(false));
  }, []);

  if (checking) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center text-gray-500">
        <Loader2 size={20} className="animate-spin mr-2" /> Checking setup…
      </div>
    );
  }

  const STEP_META = [
    {
      icon: <Building2 size={20} className="text-blue-400" />,
      title: 'Create Your Admin Account',
      subtitle: 'Set up your organisation and the first administrator account.',
    },
    {
      icon: <Brain size={20} className="text-purple-400" />,
      title: 'Configure LLM Provider',
      subtitle: 'Choose and configure the AI model that powers extraction and classification.',
    },
    {
      icon: <Folder size={20} className="text-yellow-400" />,
      title: 'Set Up Ingestion Source',
      subtitle: 'Tell DMSAI where to automatically pick up new documents.',
    },
    {
      icon: <CheckCircle2 size={20} className="text-green-400" />,
      title: "You're All Set",
      subtitle: 'Setup complete — choose where to go next.',
    },
  ];

  const meta = STEP_META[step];

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
      <div className="w-full max-w-lg">

        {/* Header */}
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-2xl bg-blue-600/20 mb-3">
            <FileText size={24} className="text-blue-400" />
          </div>
          <h1 className="text-2xl font-bold text-white">DMSAI Setup</h1>
          <p className="text-sm text-gray-500 mt-1">First-time configuration wizard</p>
        </div>

        {/* Step indicator */}
        <StepBar current={step} />

        {/* Card */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 shadow-xl">
          <div className="flex items-center gap-3 mb-5">
            <div className="w-9 h-9 rounded-lg bg-gray-800 border border-gray-700 flex items-center justify-center shrink-0">
              {meta.icon}
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">{meta.title}</h2>
              <p className="text-xs text-gray-500 mt-0.5">{meta.subtitle}</p>
            </div>
          </div>

          {step === 0 && (
            <Step1
              state={state}
              setState={setState}
              onNext={() => setStep(1)}
            />
          )}
          {step === 1 && (
            <Step2
              state={state}
              setState={setState}
              onNext={() => setStep(2)}
              onBack={() => setStep(0)}
            />
          )}
          {step === 2 && (
            <Step3
              state={state}
              setState={setState}
              onNext={() => setStep(3)}
              onBack={() => setStep(1)}
            />
          )}
          {step === 3 && (
            <Step4 />
          )}
        </div>

        <p className="text-center text-xs text-gray-600 mt-4">
          Step {step + 1} of {STEPS.length} — DMSAI v0.3
        </p>
      </div>
    </div>
  );
}
