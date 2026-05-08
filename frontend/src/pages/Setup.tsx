import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FileText, Building2, User, Lock, ChevronRight, Brain, Folder,
  Mail, CheckCircle2, ArrowRight, Loader2, Wifi, WifiOff, SkipForward,
  Upload, LayoutDashboard, Settings,
} from 'lucide-react';
import { api } from '../api';
import { useAuth } from '../auth';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
type LLMProvider = 'ollama' | 'litellm';
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
  ollamaUrl: string;
  ollamaModel: string;
  litellmUrl: string;
  litellmApiKey: string;
  litellmModel: string;

  // Step 3 — Ingestion
  ingestionType: IngestionType;
  directoryPath: string;
  imapHost: string;
  imapPort: string;
  imapUser: string;
  imapPassword: string;
  imapFolder: string;
}

const INITIAL: StepState = {
  orgName: '', fullName: '', email: '', password: '', confirmPassword: '',
  llmProvider: 'ollama',
  ollamaUrl: 'http://localhost:11434', ollamaModel: 'gemma3:27b',
  litellmUrl: 'http://localhost:4000', litellmApiKey: '', litellmModel: '',
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

  const set = (k: keyof StepState) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setState({ ...state, [k]: e.target.value });

  const saveConfig = async () => {
    if (state.llmProvider === 'ollama') {
      await api.updateSystemConfig('llm_provider', 'ollama');
      await api.updateSystemConfig('ollama_base_url', state.ollamaUrl);
      await api.updateSystemConfig('llm_model', state.ollamaModel);
    } else {
      await api.updateSystemConfig('llm_provider', 'litellm');
      await api.updateSystemConfig('litellm_base_url', state.litellmUrl);
      await api.updateSystemConfig('litellm_api_key', state.litellmApiKey);
      if (state.litellmModel) {
        await api.updateSystemConfig('litellm_model', state.litellmModel);
      }
    }
  };

  const handleTest = async () => {
    setTestResult('testing');
    try {
      await saveConfig();
      const health = await api.getPipelineHealth();
      const up = Object.values(health).some((n: any) => n.status === 'ok' || n.status === 'healthy');
      setTestResult(up ? 'ok' : 'fail');
    } catch {
      setTestResult('fail');
    }
  };

  const handleNext = async () => {
    setError('');
    setSaving(true);
    try {
      await saveConfig();
      onNext();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to save LLM settings';
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  const provider = state.llmProvider;

  return (
    <div className="space-y-5">
      {/* Provider toggle */}
      <div>
        <Label>LLM Provider</Label>
        <div className="grid grid-cols-2 gap-3">
          {(['ollama', 'litellm'] as LLMProvider[]).map(p => (
            <button
              key={p}
              type="button"
              onClick={() => setState({ ...state, llmProvider: p })}
              className={cls(
                'flex flex-col items-start gap-1 px-4 py-3 rounded-lg border text-sm font-medium transition-all',
                provider === p
                  ? 'bg-blue-600/20 border-blue-500 text-blue-300'
                  : 'bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-600',
              )}
            >
              <span className="font-semibold capitalize">{p === 'litellm' ? 'LiteLLM / Cloud' : 'Ollama (Local)'}</span>
              <span className="text-xs text-gray-500">
                {p === 'ollama' ? 'Run models locally via Ollama' : 'Use any cloud API via LiteLLM proxy'}
              </span>
            </button>
          ))}
        </div>
      </div>

      {provider === 'ollama' ? (
        <>
          <div>
            <Label>Ollama Base URL</Label>
            <Input
              type="url" value={state.ollamaUrl} onChange={set('ollamaUrl')}
              placeholder="http://localhost:11434"
            />
            <p className="mt-1 text-xs text-gray-500">The URL where your Ollama server is running.</p>
          </div>
          <div>
            <Label>Model Name</Label>
            <Input
              type="text" value={state.ollamaModel} onChange={set('ollamaModel')}
              placeholder="gemma3:27b"
            />
            <p className="mt-1 text-xs text-gray-500">
              Run <code className="text-gray-400 bg-gray-800 px-1 rounded">ollama pull gemma3:27b</code> first if you haven't already.
            </p>
          </div>
        </>
      ) : (
        <>
          <div>
            <Label>LiteLLM Proxy URL</Label>
            <Input
              type="url" value={state.litellmUrl} onChange={set('litellmUrl')}
              placeholder="http://localhost:4000"
            />
          </div>
          <div>
            <Label>API Key</Label>
            <Input
              type="password" value={state.litellmApiKey} onChange={set('litellmApiKey')}
              placeholder="sk-… or your provider key"
            />
          </div>
          <div>
            <Label>Model Identifier (optional)</Label>
            <Input
              type="text" value={state.litellmModel} onChange={set('litellmModel')}
              placeholder="gemini/gemini-1.5-pro"
            />
            <p className="mt-1 text-xs text-gray-500">
              Leave empty to use the LiteLLM proxy default. See LiteLLM docs for provider/model strings.
            </p>
          </div>
        </>
      )}

      {/* Test connection */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleTest}
          disabled={testResult === 'testing'}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-300 hover:border-gray-600 disabled:opacity-50 transition-colors"
        >
          {testResult === 'testing' ? <Loader2 size={14} className="animate-spin" /> : <Wifi size={14} />}
          Test Connection
        </button>
        {testResult === 'ok' && (
          <span className="flex items-center gap-1 text-green-400 text-sm">
            <CheckCircle2 size={14} /> Pipeline reachable
          </span>
        )}
        {testResult === 'fail' && (
          <span className="flex items-center gap-1 text-yellow-400 text-sm">
            <WifiOff size={14} /> Could not reach pipeline — you can still continue
          </span>
        )}
      </div>

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
          {saving ? 'Saving…' : 'Save & Continue'}
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
function Step4({ onFinish }: { onFinish: () => void }) {
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
            <Step4 onFinish={() => navigate('/')} />
          )}
        </div>

        <p className="text-center text-xs text-gray-600 mt-4">
          Step {step + 1} of {STEPS.length} — DMSAI v0.3
        </p>
      </div>
    </div>
  );
}
