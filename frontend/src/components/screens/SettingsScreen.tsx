import { useAppState } from '@/context/AppContext';
import { useI18n } from '@/context/I18nContext';
import { api } from '@/lib/api';
import type { AppSettings, ModelInfo, SetupStatus } from '@/types/backend';
import { useState, useEffect, useRef } from 'react';
import {
  ArrowLeft,
  Check,
  CheckCircle2,
  Download,
  Loader2,
  RefreshCw,
  Save,
  AlertCircle,
  Cpu,
  FolderOpen,
  Package,
  Sliders,
  Zap,
  Maximize2,
  Users,
} from 'lucide-react';

const WHISPER_MODELS = ['tiny', 'base', 'small', 'medium', 'large-v2', 'large-v3'];

const COMPUTE_PRESET_IDS = ['int8', 'float16', 'float32'] as const;
const COMPUTE_LABEL_KEYS: Record<string, string> = {
  int8: 'settings.compute.recommended',
  float16: 'settings.compute.gpuFast',
  float32: 'settings.compute.maxPrecision',
};
const COMPUTE_NOTE_KEYS: Record<string, string> = {
  int8: 'settings.compute.recommendedNote',
  float16: 'settings.compute.gpuFastNote',
  float32: 'settings.compute.maxPrecisionNote',
};

const LLM_MODEL_PATHS: Record<string, string> = {
  'qwen2.5-1.5b': 'models/qwen2.5-1.5b-instruct-q4_k_m.gguf',
  'qwen2.5-3b': 'models/qwen2.5-3b-instruct-q4_k_m.gguf',
  'qwen2.5-7b': 'models/qwen2.5-7b-instruct-q4_k_m.gguf',
};

const normalizeComputeType = (value: string): string => {
  const known = new Set(COMPUTE_PRESET_IDS);
  if (value === 'int8_float16') return 'int8';
  return known.has(value as typeof COMPUTE_PRESET_IDS[number]) ? value : 'int8';
};

const DIARIZATION_PROFILE_IDS = ['fast', 'balanced', 'quality'] as const;
const DIAR_LABEL_KEYS: Record<string, string> = {
  fast: 'settings.diar.fast',
  balanced: 'settings.diar.balanced',
  quality: 'settings.diar.quality',
};
const DIAR_NOTE_KEYS: Record<string, string> = {
  fast: 'settings.diar.fastNote',
  balanced: 'settings.diar.balancedNote',
  quality: 'settings.diar.qualityNote',
};

// ── Model download tracker (local to settings screen) ────────────────────────
interface SettingsDownload {
  kind: 'whisper' | 'llm';
  model_id: string;
  download_id: string;
  label: string;
  pct: number;
  status: 'running' | 'done' | 'failed';
}

const SettingsScreen = () => {
  const { setScreen, settings, saveSettings, refreshSettings } = useAppState();
  const { t } = useI18n();

  const [form, setForm] = useState<AppSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Models section state
  const [setupStatus, setSetupStatus] = useState<SetupStatus | null>(null);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [activeDownloads, setActiveDownloads] = useState<SettingsDownload[]>([]);
  const handledDownloadsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (settings) {
      setForm({ ...settings, whisper_compute_type: normalizeComputeType(settings.whisper_compute_type) });
    }
  }, [settings]);

  const loadModelsStatus = () => {
    setModelsLoading(true);
    api.getSetupStatus()
      .then(setSetupStatus)
      .catch(() => {})
      .finally(() => setModelsLoading(false));
  };

  useEffect(() => {
    loadModelsStatus();
  }, []);

  useEffect(() => {
    if (activeDownloads.length === 0) return;
    if (activeDownloads.every((d) => d.status !== 'running')) return;
    const id = setInterval(async () => {
      const updated = await Promise.all(
        activeDownloads.map(async (d) => {
          if (d.status !== 'running') return d;
          try {
            const s = await api.pollDownload(d.download_id);
            return { ...d, pct: s.progress_pct, status: s.status };
          } catch {
            return d;
          }
        })
      );
      setActiveDownloads(updated);
    }, 1000);
    return () => clearInterval(id);
  }, [activeDownloads]);

  useEffect(() => {
    const pendingAutoSaves: Promise<void>[] = [];
    let requiresStatusRefresh = false;

    activeDownloads.forEach((download) => {
      if (download.status !== 'done') return;
      if (handledDownloadsRef.current.has(download.download_id)) return;
      handledDownloadsRef.current.add(download.download_id);
      requiresStatusRefresh = true;

      if (download.kind !== 'llm') return;
      const targetPath = LLM_MODEL_PATHS[download.model_id];
      if (!targetPath) return;

      setForm((prev) => (prev ? { ...prev, llama_model_path: targetPath } : prev));
      pendingAutoSaves.push(
        saveSettings({ llama_model_path: targetPath })
          .then(() => refreshSettings())
          .catch(() => Promise.resolve())
      );
    });

    if (!requiresStatusRefresh) return;

    void Promise.allSettled(pendingAutoSaves).finally(() => {
      loadModelsStatus();
    });
  }, [activeDownloads, refreshSettings, saveSettings]);

  const downloadModel = async (kind: 'whisper' | 'llm', model: ModelInfo) => {
    try {
      const dl = await api.startDownload(kind, model.id);
      setActiveDownloads((prev) => [
        ...prev,
        { kind, model_id: model.id, download_id: dl.download_id, label: model.label, pct: 0, status: 'running' },
      ]);
    } catch {
      // ignore
    }
  };

  if (!form) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="w-5 h-5 text-primary animate-spin" />
      </div>
    );
  }

  const handleSave = async () => {
    try {
      setSaving(true);
      setError(null);
      setSaved(false);
      await saveSettings({
        whisper_model: form.whisper_model,
        whisper_compute_type: form.whisper_compute_type,
        llama_model_path: form.llama_model_path,
        llama_n_ctx: form.llama_n_ctx,
        llama_n_threads: form.llama_n_threads,
        diarization_profile: form.diarization_profile,
        workspace_dir: form.workspace_dir,
        fullscreen_on_maximize: form.fullscreen_on_maximize,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const set = (key: keyof AppSettings, value: string | number | boolean) =>
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));

  return (
    <div className="flex-1 flex flex-col items-center pt-[60px] px-8 pb-8 max-w-2xl mx-auto w-full gap-6 animate-fade-in overflow-y-auto">
      <button
        onClick={() => setScreen('home')}
        className="self-start glass-control flex items-center gap-1.5 text-xs text-muted-foreground/60 hover:text-foreground transition-colors duration-150 px-3 py-1.5"
      >
        <ArrowLeft className="w-3 h-3" />
        {t('settings.back')}
      </button>

      <div className="text-center w-full">
        <h2 className="font-display text-base font-semibold text-foreground/92">{t('settings.heading')}</h2>
        <p className="text-xs text-muted-foreground/40 mt-0.5">{t('settings.subtitle')}</p>
      </div>

      {/* Models */}
      <section className="w-full space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Package className="w-3.5 h-3.5 text-primary/60" />
            <p className="text-[11px] text-muted-foreground/40 uppercase tracking-widest font-medium">{t('settings.aiModels')}</p>
          </div>
          <button
            onClick={loadModelsStatus}
            disabled={modelsLoading}
            className="flex items-center gap-1 text-[10px] text-muted-foreground/40 hover:text-muted-foreground transition-colors disabled:opacity-40"
          >
            <RefreshCw className={`w-2.5 h-2.5 ${modelsLoading ? 'animate-spin' : ''}`} />
            {t('settings.refresh')}
          </button>
        </div>

        {/* Whisper models */}
        <div className="glass-panel rounded-xl p-4 space-y-3">
          <div className="flex items-center gap-1.5">
            <Zap className="w-3 h-3 text-primary/50" />
            <p className="text-[10px] text-muted-foreground/50 font-medium">{t('settings.whisperSection')}</p>
          </div>
          {modelsLoading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground/40">
              <Loader2 className="w-3 h-3 animate-spin" /> {t('settings.loading')}
            </div>
          ) : (
            <div className="space-y-1.5">
              {(setupStatus?.whisper_models ?? []).map((m) => {
                const dl = activeDownloads.find((d) => d.label === m.label);
                const isActive = m.id === form?.whisper_model;
                return (
                  <div
                    key={m.id}
                    className={`flex items-center gap-2.5 rounded-lg px-3 py-2 transition-colors ${
                      isActive ? 'bg-primary/10 border border-primary/20' : 'border border-transparent hover:bg-card/60'
                    }`}
                  >
                    <span className={`text-xs font-medium flex-1 ${isActive ? 'text-primary' : 'text-foreground/70'}`}>
                      {m.label}
                    </span>
                    <span className="text-[10px] font-mono text-muted-foreground/40">
                      {m.size_mb >= 1024 ? `${(m.size_mb / 1024).toFixed(1)} GB` : `${m.size_mb} MB`}
                    </span>
                    {m.is_cached ? (
                      <CheckCircle2 className="w-3 h-3 text-success/60 shrink-0" />
                    ) : dl ? (
                      <span className={`text-[10px] font-mono ${dl.status === 'done' ? 'text-success/70' : dl.status === 'failed' ? 'text-destructive/70' : 'text-primary/60'}`}>
                        {dl.status === 'running' ? `${dl.pct.toFixed(0)}%` : dl.status === 'done' ? '✓' : '✗'}
                      </span>
                    ) : m.compatible ? (
                      <button
                        onClick={() => void downloadModel('whisper', m)}
                        title={t('settings.download')}
                        className="text-muted-foreground/30 hover:text-primary transition-colors"
                      >
                        <Download className="w-3 h-3" />
                      </button>
                    ) : (
                      <span className="text-[9px] text-muted-foreground/25">{t('settings.incompatible')}</span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* LLM models */}
        <div className="glass-panel rounded-xl p-4 space-y-3">
          <div className="flex items-center gap-1.5">
            <Sliders className="w-3 h-3 text-primary/50" />
            <p className="text-[10px] text-muted-foreground/50 font-medium">{t('settings.llmSection')}</p>
          </div>
          {modelsLoading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground/40">
              <Loader2 className="w-3 h-3 animate-spin" /> {t('settings.loading')}
            </div>
          ) : (
            <div className="space-y-1.5">
              {(setupStatus?.llm_models ?? []).filter((m) => m.id !== 'none').map((m) => {
                const dl = activeDownloads.find((d) => d.label === m.label);
                return (
                  <div
                    key={m.id}
                    className="flex items-center gap-2.5 rounded-lg px-3 py-2 border border-transparent hover:bg-card/60 transition-colors"
                  >
                    <span className="text-xs font-medium flex-1 text-foreground/70">{m.label}</span>
                    <span className="text-[10px] font-mono text-muted-foreground/40">
                      {m.size_mb >= 1024 ? `${(m.size_mb / 1024).toFixed(1)} GB` : `${m.size_mb} MB`}
                    </span>
                    {m.is_cached ? (
                      <CheckCircle2 className="w-3 h-3 text-success/60 shrink-0" />
                    ) : dl ? (
                      <span className={`text-[10px] font-mono ${dl.status === 'done' ? 'text-success/70' : dl.status === 'failed' ? 'text-destructive/70' : 'text-primary/60'}`}>
                        {dl.status === 'running' ? `${dl.pct.toFixed(0)}%` : dl.status === 'done' ? '✓' : '✗'}
                      </span>
                    ) : m.compatible ? (
                      <button
                        onClick={() => void downloadModel('llm', m)}
                        title={t('settings.download')}
                        className="text-muted-foreground/30 hover:text-primary transition-colors"
                      >
                        <Download className="w-3 h-3" />
                      </button>
                    ) : (
                      <span className="text-[9px] text-muted-foreground/25">{t('settings.incompatible')}</span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </section>

      {/* Diarization */}
      <section className="w-full space-y-3">
        <div className="flex items-center gap-2">
          <Users className="w-3.5 h-3.5 text-primary/60" />
          <p className="text-[11px] text-muted-foreground/40 uppercase tracking-widest font-medium">{t('settings.diarization')}</p>
        </div>
        <div className="glass-panel rounded-xl p-4 space-y-3">
          {DIARIZATION_PROFILE_IDS.map((id) => (
            <button
              key={id}
              onClick={() => set('diarization_profile', id)}
              className={`w-full text-left rounded-lg border px-3 py-2.5 transition-all ${
                form.diarization_profile === id
                  ? 'border-primary/40 bg-primary/10'
                  : 'border-border/40 bg-secondary/30 hover:border-primary/20'
              }`}
            >
              <p className={`text-xs font-medium ${form.diarization_profile === id ? 'text-primary' : 'text-foreground/80'}`}>
                {t(DIAR_LABEL_KEYS[id])}
              </p>
              <p className="text-[10px] text-muted-foreground/45 mt-1">{t(DIAR_NOTE_KEYS[id])}</p>
            </button>
          ))}
        </div>
      </section>

      {/* Whisper */}
      <section className="w-full space-y-3">
        <div className="flex items-center gap-2">
          <Cpu className="w-3.5 h-3.5 text-primary/60" />
          <p className="text-[11px] text-muted-foreground/40 uppercase tracking-widest font-medium">{t('settings.whisperConfig')}</p>
        </div>
        <div className="glass-panel rounded-xl p-4 space-y-4">
          <div>
            <label className="text-xs text-foreground/70 mb-2 block">{t('settings.model')}</label>
            <div className="grid grid-cols-3 gap-2">
              {WHISPER_MODELS.map((m) => (
                <button
                  key={m}
                  onClick={() => set('whisper_model', m)}
                  className={`px-3 py-2 rounded-lg text-xs font-medium transition-all duration-150 ${
                    form.whisper_model === m
                      ? 'bg-primary/15 border border-primary/40 text-primary glow-violet-sm'
                      : 'bg-secondary/40 border border-border/40 text-muted-foreground/60 hover:border-primary/20 hover:text-foreground'
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
            <p className="text-[10px] text-muted-foreground/35 mt-1.5">
              {t('settings.modelHint')}
            </p>
          </div>

          <div>
            <label className="text-xs text-foreground/70 mb-2 block">{t('settings.computeType')}</label>
            <div className="grid gap-2 sm:grid-cols-3">
              {COMPUTE_PRESET_IDS.map((id) => (
                <button
                  key={id}
                  onClick={() => set('whisper_compute_type', id)}
                  className={`rounded-lg border px-3 py-2 text-left transition-all duration-150 ${
                    form.whisper_compute_type === id
                      ? 'border-primary/40 bg-primary/10'
                      : 'border-border/40 bg-secondary/30 hover:border-primary/20'
                  }`}
                >
                  <p
                    className={`text-xs font-medium ${
                      form.whisper_compute_type === id ? 'text-primary' : 'text-foreground/80'
                    }`}
                  >
                    {t(COMPUTE_LABEL_KEYS[id])}
                  </p>
                  <p className="mt-1 text-[10px] text-muted-foreground/45">{t(COMPUTE_NOTE_KEYS[id])}</p>
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* LLM */}
      <section className="w-full space-y-3">
        <div className="flex items-center gap-2">
          <Sliders className="w-3.5 h-3.5 text-primary/60" />
          <p className="text-[11px] text-muted-foreground/40 uppercase tracking-widest font-medium">{t('settings.llmConfig')}</p>
        </div>
        <div className="glass-panel rounded-xl p-4 space-y-4">
          <div>
            <label className="text-xs text-foreground/70 mb-1.5 block">{t('settings.llmPath')}</label>
            <input
              type="text"
              value={form.llama_model_path}
              onChange={(e) => set('llama_model_path', e.target.value)}
              placeholder="models/postprocess.gguf"
              className="w-full font-mono text-xs bg-secondary/40 border border-border/60 rounded-lg px-3 py-2.5 outline-none focus:border-primary/40 focus:ring-1 focus:ring-primary/20 placeholder:text-muted-foreground/25 transition-all"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-foreground/70 mb-1.5 block">{t('settings.contextTokens')}</label>
              <input
                type="number"
                min={512}
                max={32768}
                value={form.llama_n_ctx}
                onChange={(e) => set('llama_n_ctx', parseInt(e.target.value, 10) || 2048)}
                className="w-full font-mono text-xs bg-secondary/40 border border-border/60 rounded-lg px-3 py-2.5 outline-none focus:border-primary/40 focus:ring-1 focus:ring-primary/20 transition-all"
              />
            </div>
            <div>
              <label className="text-xs text-foreground/70 mb-1.5 block">{t('settings.cpuThreads')}</label>
              <input
                type="number"
                min={1}
                max={32}
                value={form.llama_n_threads}
                onChange={(e) => set('llama_n_threads', parseInt(e.target.value, 10) || 4)}
                className="w-full font-mono text-xs bg-secondary/40 border border-border/60 rounded-lg px-3 py-2.5 outline-none focus:border-primary/40 focus:ring-1 focus:ring-primary/20 transition-all"
              />
            </div>
          </div>
        </div>
      </section>

      {/* Workspace */}
      <section className="w-full space-y-3">
        <div className="flex items-center gap-2">
          <FolderOpen className="w-3.5 h-3.5 text-primary/60" />
          <p className="text-[11px] text-muted-foreground/40 uppercase tracking-widest font-medium">{t('settings.storage')}</p>
        </div>
        <div className="glass-panel rounded-xl p-4">
          <label className="text-xs text-foreground/70 mb-1.5 block">{t('settings.workDir')}</label>
          <input
            type="text"
            value={form.workspace_dir}
            onChange={(e) => set('workspace_dir', e.target.value)}
            placeholder="workspace"
            className="w-full font-mono text-xs bg-secondary/40 border border-border/60 rounded-lg px-3 py-2.5 outline-none focus:border-primary/40 focus:ring-1 focus:ring-primary/20 placeholder:text-muted-foreground/25 transition-all"
          />
          <p className="text-[10px] text-muted-foreground/35 mt-1.5">
            {t('settings.workDirHint')}
          </p>
        </div>
      </section>

      {/* Window behavior */}
      <section className="w-full space-y-3">
        <div className="flex items-center gap-2">
          <Maximize2 className="w-3.5 h-3.5 text-primary/60" />
          <p className="text-[11px] text-muted-foreground/40 uppercase tracking-widest font-medium">{t('settings.window')}</p>
        </div>
        <div className="glass-panel rounded-xl p-4 space-y-3">
          <label className="flex items-center justify-between gap-3 cursor-pointer">
            <div>
              <p className="text-xs text-foreground/80">{t('settings.fullscreenMaximize')}</p>
              <p className="text-[10px] text-muted-foreground/40 mt-1">
                {t('settings.fullscreenMaximizeHint')}
              </p>
            </div>
            <button
              type="button"
              onClick={() => set('fullscreen_on_maximize', !form.fullscreen_on_maximize)}
              className={`w-11 h-6 rounded-full transition-colors relative ${
                form.fullscreen_on_maximize ? 'bg-primary' : 'bg-secondary/70 border border-border/60'
              }`}
              title={t('settings.fullscreenToggle')}
            >
              <span
                className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${
                  form.fullscreen_on_maximize ? 'left-5' : 'left-0.5'
                }`}
              />
            </button>
          </label>
        </div>
      </section>

      {/* Save */}
      <div className="w-full space-y-2 pb-4">
        {error && (
          <p className="text-xs text-destructive flex items-center gap-1.5">
            <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            {error}
          </p>
        )}
        <button
          onClick={() => void handleSave()}
          disabled={saving}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 btn-glow transition-all duration-200"
        >
          {saving ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              {t('settings.saving')}
            </>
          ) : saved ? (
            <>
              <Check className="w-4 h-4" />
              {t('settings.savedDone')}
            </>
          ) : (
            <>
              <Save className="w-4 h-4" />
              {t('settings.saveChanges')}
            </>
          )}
        </button>
      </div>
    </div>
  );
};

export default SettingsScreen;
