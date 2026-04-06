import { useAppState } from '@/context/AppContext';
import { api } from '@/lib/api';
import type { DownloadStatus, ModelInfo, SetupStatus } from '@/types/backend';
import {
  AlertCircle,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronRight,
  Cpu,
  Download,
  Loader2,
  MemoryStick,
  MonitorSpeaker,
  Sliders,
  Sparkles,
  Zap,
} from 'lucide-react';
import diaricatLogo from '@/assets/diaricat-logo.png';
import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react';

type WizardStep = 'scanning' | 'welcome' | 'whisper' | 'llm' | 'token' | 'downloading' | 'done';

interface ActiveDownload {
  kind: 'whisper' | 'llm';
  model_id: string;
  download_id: string;
  status: DownloadStatus;
  label: string;
}

const DIARIZATION_PROFILES = [
  { id: 'fast', label: 'Rapido', description: 'Menor uso de CPU/RAM. Menor precision en cambios cortos.' },
  { id: 'balanced', label: 'Equilibrado', description: 'Balance recomendado entre calidad y velocidad.' },
  { id: 'quality', label: 'Calidad', description: 'Mayor precision en speakers. Mayor costo de CPU.' },
];

const fmtBytes = (bytes: number): string => {
  if (bytes === 0) return '0 MB';
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(0)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
};

const fmtMb = (mb: number): string => {
  if (mb === 0) return '-';
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${mb} MB`;
};

const formatGpuStatus = (specs: SetupStatus['specs']): string => {
  if (!specs.has_gpu) {
    return 'No detectada (modo CPU)';
  }
  if (specs.gpu_usable) {
    const suffix = specs.gpu_vram_gb > 0 ? ` - ${specs.gpu_vram_gb} GB VRAM` : '';
    return `${specs.gpu_name ?? 'GPU detectada'}${suffix}`;
  }
  return `${specs.gpu_name ?? 'GPU detectada'} - CUDA no disponible en este entorno`;
};

const ModelCard = ({
  model,
  selected,
  recommended,
  onSelect,
}: {
  model: ModelInfo;
  selected: boolean;
  recommended: boolean;
  onSelect: () => void;
}) => {
  const locked = !model.compatible;

  return (
    <button
      onClick={locked ? undefined : onSelect}
      disabled={locked}
      className={`w-full text-left rounded-xl border p-3.5 transition-all duration-150 relative group ${
        locked
          ? 'border-border/20 bg-card/20 opacity-40 cursor-not-allowed'
          : selected
          ? 'border-primary/50 bg-primary/8 shadow-[0_0_0_1px_hsl(var(--primary)/0.2)]'
          : 'glass-control border-border/40 hover:border-primary/25 hover:bg-primary/[0.03] cursor-pointer'
      }`}
    >
      {recommended && !locked && (
        <span className="absolute -top-2 right-3 px-2 py-0.5 rounded-full bg-primary text-primary-foreground text-[9px] font-semibold tracking-wide uppercase">
          Recomendado
        </span>
      )}
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex-shrink-0">
          <div className={`w-4 h-4 rounded-full border-2 ${selected ? 'border-primary bg-primary' : 'border-border/60'}`}>
            {selected && <div className="w-1.5 h-1.5 rounded-full bg-white mx-auto mt-[3px]" />}
          </div>
        </div>
        <div className="flex-1 min-w-0 space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <span className={`text-sm font-medium ${selected ? 'text-primary' : 'text-foreground/85'}`}>{model.label}</span>
            <span className="text-[10px] font-mono text-muted-foreground/50 shrink-0">{fmtMb(model.size_mb)}</span>
          </div>
          <p className="text-[11px] text-muted-foreground/55 leading-relaxed">{model.description}</p>
          {model.is_cached && (
            <span className="inline-flex items-center gap-1 text-[9px] text-success/70">
              <CheckCircle2 className="w-2.5 h-2.5" />
              Descargado
            </span>
          )}
        </div>
      </div>
    </button>
  );
};

const DownloadCard = ({ dl }: { dl: ActiveDownload }) => {
  const pct = dl.status.progress_pct;
  const done = dl.status.status === 'done';
  const failed = dl.status.status === 'failed';
  return (
    <div className={`rounded-xl border p-4 space-y-2.5 ${done ? 'glass-panel border-success/30' : failed ? 'glass-panel border-destructive/30' : 'glass-panel border-border/40'}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-foreground/85 truncate">{dl.label}</span>
        <span className={`text-[10px] font-mono shrink-0 ${done ? 'text-success/80' : failed ? 'text-destructive/80' : 'text-muted-foreground/50'}`}>
          {done ? 'Listo' : failed ? 'Error' : `${pct.toFixed(0)}%`}
        </span>
      </div>
      {!done && !failed && (
        <>
          <div className="h-1 rounded-full bg-border/40 overflow-hidden">
            <div className="h-full rounded-full bg-primary transition-all duration-300" style={{ width: `${Math.min(pct, 100)}%` }} />
          </div>
          <div className="flex justify-between text-[10px] text-muted-foreground/40">
            <span>{fmtBytes(dl.status.downloaded_bytes)}</span>
            <span>{dl.status.total_bytes > 0 ? fmtBytes(dl.status.total_bytes) : '-'}</span>
          </div>
        </>
      )}
      {failed && (
        <p className="text-[10px] text-destructive/75 leading-relaxed break-words">
          {dl.status.error ?? 'No se pudo completar la descarga.'}
        </p>
      )}
    </div>
  );
};

const SetupWizard = () => {
  const { setScreen, refreshSettings } = useAppState();
  const [step, setStep] = useState<WizardStep>('scanning');
  const [setupStatus, setSetupStatus] = useState<SetupStatus | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const [selectedWhisper, setSelectedWhisper] = useState<string>('small');
  const [selectedLlm, setSelectedLlm] = useState<string>('none');
  const [selectedDiarization, setSelectedDiarization] = useState<string>('balanced');
  const [downloads, setDownloads] = useState<ActiveDownload[]>([]);
  const [completing, setCompleting] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    api
      .getSetupStatus()
      .then((status) => {
        setSetupStatus(status);
        setSelectedWhisper(status.recommendation.whisper_id);
        setSelectedLlm(status.recommendation.llm_id);
        setStep('welcome');
      })
      .catch((err: Error) => {
        setScanError(err.message);
        setStep('welcome');
      });
  }, []);

  const pollDownloads = useCallback(() => {
    downloads.forEach(async (dl) => {
      if (dl.status.status !== 'running') return;
      try {
        const updated = await api.pollDownload(dl.download_id);
        setDownloads((prev) => prev.map((d) => (d.download_id === dl.download_id ? { ...d, status: updated } : d)));
      } catch {
        // ignore transient poll errors
      }
    });
  }, [downloads]);

  useEffect(() => {
    if (step !== 'downloading') return;
    pollRef.current = setInterval(pollDownloads, 1000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [step, pollDownloads]);

  const buildFailedDownload = useCallback(
    (kind: 'whisper' | 'llm', model_id: string, label: string, error: unknown): ActiveDownload => {
      const message = error instanceof Error ? error.message : 'No se pudo iniciar la descarga.';
      const download_id = `failed-${kind}-${model_id}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
      return {
        kind,
        model_id,
        label,
        download_id,
        status: {
          download_id,
          status: 'failed',
          downloaded_bytes: 0,
          total_bytes: 0,
          progress_pct: 0,
          error: message,
        },
      };
    },
    []
  );

  const hasRunning = downloads.some((d) => d.status.status === 'running');
  const hasFailed = downloads.some((d) => d.status.status === 'failed');
  const failedCount = downloads.filter((d) => d.status.status === 'failed').length;
  const allSucceeded = downloads.length > 0 && downloads.every((d) => d.status.status === 'done');

  const startDownloads = useCallback(async () => {
    const pending: ActiveDownload[] = [];
    const whisperModel = setupStatus?.whisper_models.find((m) => m.id === selectedWhisper);
    const llmModel = setupStatus?.llm_models.find((m) => m.id === selectedLlm);

    if (whisperModel && !whisperModel.is_cached) {
      try {
        const dl = await api.startDownload('whisper', selectedWhisper);
        pending.push({ kind: 'whisper', model_id: selectedWhisper, download_id: dl.download_id, status: dl, label: whisperModel.label });
      } catch (err) {
        pending.push(buildFailedDownload('whisper', selectedWhisper, whisperModel.label, err));
      }
    }
    if (llmModel && selectedLlm !== 'none' && !llmModel.is_cached) {
      try {
        const dl = await api.startDownload('llm', selectedLlm);
        pending.push({ kind: 'llm', model_id: selectedLlm, download_id: dl.download_id, status: dl, label: llmModel.label });
      } catch (err) {
        pending.push(buildFailedDownload('llm', selectedLlm, llmModel.label, err));
      }
    }
    setDownloads(pending);
    setStep('downloading');
  }, [selectedWhisper, selectedLlm, setupStatus, buildFailedDownload]);

  const retryFailedDownloads = useCallback(async () => {
    setRetrying(true);
    try {
      const updated = await Promise.all(
        downloads.map(async (dl) => {
          if (dl.status.status !== 'failed') return dl;
          try {
            const restarted = await api.startDownload(dl.kind, dl.model_id);
            return { ...dl, download_id: restarted.download_id, status: restarted };
          } catch (err) {
            return buildFailedDownload(dl.kind, dl.model_id, dl.label, err);
          }
        })
      );
      setDownloads(updated);
    } finally {
      setRetrying(false);
    }
  }, [downloads, buildFailedDownload]);

  const skipToDownloading = useCallback(() => {
    setDownloads([]);
    setStep('downloading');
  }, []);

  const finishSetup = useCallback(async () => {
    try {
      setCompleting(true);
      await api.completeSetup({
        whisper_model: selectedWhisper,
        llm_model_id: selectedLlm !== 'none' ? selectedLlm : undefined,
        diarization_profile: selectedDiarization,
      });
      await refreshSettings();
      setStep('done');
    } catch {
      setCompleting(false);
    }
  }, [selectedWhisper, selectedLlm, selectedDiarization, refreshSettings]);

  const goHome = useCallback(() => setScreen('home'), [setScreen]);
  const specs = setupStatus?.specs;

  if (step === 'scanning') {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-5 animate-fade-in">
        <img src={diaricatLogo} alt="Diaricat" className="w-14 h-14 rounded-2xl opacity-80" draggable={false} />
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-5 h-5 text-primary animate-spin" />
          <p className="text-xs text-muted-foreground/50 tracking-wide">Analizando sistema...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col items-center overflow-y-auto">
      <div className="w-full max-w-xl px-8 py-6 flex flex-col gap-6 animate-fade-in glass-panel rounded-2xl my-3">
        {step === 'welcome' && (
          <>
            <div className="flex flex-col items-center gap-4 text-center pt-2">
              <img src={diaricatLogo} alt="Diaricat" className="w-16 h-16 rounded-2xl" draggable={false} />
              <div>
                <h1 className="font-display text-xl font-semibold text-foreground/92 tracking-tight">Bienvenido a Diaricat</h1>
                <p className="text-xs text-muted-foreground/50 mt-1">Vamos a configurar los modelos segun tu sistema.</p>
              </div>
            </div>

            {scanError && (
              <div className="flex items-start gap-2 rounded-xl border border-destructive/30 bg-destructive/5 px-3.5 py-3 text-xs text-destructive/80">
                <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                No se pudo leer el sistema: {scanError}
              </div>
            )}

            {specs && (
              <div className="glass-panel rounded-xl p-4 grid grid-cols-2 gap-3">
                <div className="flex items-center gap-2.5">
                  <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center">
                    <MemoryStick className="w-3.5 h-3.5 text-primary/70" />
                  </div>
                  <div>
                    <p className="text-[10px] text-muted-foreground/40 uppercase tracking-wider">RAM</p>
                    <p className="text-xs font-medium text-foreground/80">{specs.ram_gb} GB</p>
                  </div>
                </div>
                <div className="flex items-center gap-2.5">
                  <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center">
                    <Cpu className="w-3.5 h-3.5 text-primary/70" />
                  </div>
                  <div>
                    <p className="text-[10px] text-muted-foreground/40 uppercase tracking-wider">CPU</p>
                    <p className="text-xs font-medium text-foreground/80">{specs.cpu_cores} cores</p>
                  </div>
                </div>
                <div className="flex items-center gap-2.5 col-span-2">
                  <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center">
                    <MonitorSpeaker className="w-3.5 h-3.5 text-primary/70" />
                  </div>
                  <div>
                    <p className="text-[10px] text-muted-foreground/40 uppercase tracking-wider">GPU</p>
                    <p className="text-xs font-medium text-foreground/80">{formatGpuStatus(specs)}</p>
                  </div>
                </div>
              </div>
            )}

            <button onClick={() => setStep('whisper')} className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 btn-glow transition-all duration-200">
              Empezar configuracion
              <ArrowRight className="w-4 h-4" />
            </button>
            <button onClick={goHome} className="text-xs text-muted-foreground/40 hover:text-muted-foreground transition-colors text-center">
              Omitir y configurar despues
            </button>
          </>
        )}

        {step === 'whisper' && (
          <>
            <StepHeader icon={<Zap className="w-4 h-4 text-primary/70" />} step="1 / 3" title="Modelo de transcripcion" subtitle="Whisper convierte audio a texto. Modelos mas grandes son mas precisos y mas pesados." />
            <div className="flex flex-col gap-2">
              {(setupStatus?.whisper_models ?? []).map((m) => (
                <ModelCard key={m.id} model={m} selected={selectedWhisper === m.id} recommended={m.id === setupStatus?.recommendation.whisper_id} onSelect={() => setSelectedWhisper(m.id)} />
              ))}
            </div>
            <StepNav onBack={() => setStep('welcome')} onNext={() => setStep('llm')} />
          </>
        )}

        {step === 'llm' && (
          <>
            <StepHeader icon={<Sliders className="w-4 h-4 text-primary/70" />} step="2 / 3" title="Modelo de IA (correccion y resumen)" subtitle="Modelo opcional para corregir texto y generar resumen." />
            <div className="flex flex-col gap-2">
              {(setupStatus?.llm_models ?? []).map((m) => (
                <ModelCard key={m.id} model={m} selected={selectedLlm === m.id} recommended={m.id === setupStatus?.recommendation.llm_id} onSelect={() => setSelectedLlm(m.id)} />
              ))}
            </div>
            <StepNav onBack={() => setStep('whisper')} onNext={() => setStep('token')} />
          </>
        )}

        {step === 'token' && (
          <>
            <StepHeader
              icon={<MonitorSpeaker className="w-4 h-4 text-primary/70" />}
              step="3 / 3"
              title="Diarizacion local"
              subtitle="Selecciona el perfil de calidad/rendimiento para multi-speaker en local."
            />
            <div className="glass-panel rounded-xl p-4 space-y-3">
              <div className="flex items-center gap-1.5">
                <MonitorSpeaker className="w-3.5 h-3.5 text-primary/60" />
                <p className="text-[10px] text-muted-foreground/50 font-medium">Perfil de diarizacion local</p>
              </div>
              <div className="space-y-2">
                {DIARIZATION_PROFILES.map((profile) => (
                  <button
                    key={profile.id}
                    onClick={() => setSelectedDiarization(profile.id)}
                    className={`w-full text-left rounded-lg border px-3 py-2.5 transition-all ${
                      selectedDiarization === profile.id ? 'border-primary/40 bg-primary/10' : 'border-border/40 bg-secondary/30 hover:border-primary/20'
                    }`}
                  >
                    <p className={`text-xs font-medium ${selectedDiarization === profile.id ? 'text-primary' : 'text-foreground/80'}`}>{profile.label}</p>
                    <p className="text-[10px] text-muted-foreground/45 mt-1">{profile.description}</p>
                  </button>
                ))}
              </div>
            </div>

            <div className="flex flex-col gap-2">
              <button onClick={startDownloads} className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 btn-glow transition-all duration-200">
                <Download className="w-4 h-4" />
                Descargar modelos seleccionados
              </button>
              <button onClick={skipToDownloading} className="w-full py-2.5 rounded-xl glass-control border border-border/40 text-xs text-muted-foreground/60 hover:text-foreground hover:border-border/70 transition-all">
                Omitir descargas (configurar despues)
              </button>
              <button onClick={() => setStep('llm')} className="text-xs text-muted-foreground/40 hover:text-muted-foreground transition-colors text-center">
                {'<-'} Volver
              </button>
            </div>
          </>
        )}

        {step === 'downloading' && (
          <>
            <div className="text-center pt-2 space-y-1">
              <h2 className="text-base font-semibold text-foreground/90">
                {downloads.length === 0
                  ? 'Modelos listos'
                  : hasRunning
                  ? 'Descargando modelos...'
                  : hasFailed
                  ? 'Descarga con errores'
                  : 'Descarga completada'}
              </h2>
              <p className="text-xs text-muted-foreground/45">
                {downloads.length === 0
                  ? 'Los modelos seleccionados ya estan en cache.'
                  : hasRunning
                  ? 'Esto puede tardar varios minutos segun tu conexion.'
                  : hasFailed
                  ? 'Una o mas descargas fallaron. Revisa el detalle y reintenta.'
                  : allSucceeded
                  ? 'Todos los modelos estan listos para usar.'
                  : 'Estado de descarga no disponible.'}
              </p>
            </div>
            {downloads.length === 0 ? (
              <div className="flex items-center gap-3 rounded-xl border border-success/25 bg-success/5 px-4 py-3.5">
                <CheckCircle2 className="w-4 h-4 text-success/70 shrink-0" />
                <p className="text-xs text-success/80">No hay descargas pendientes.</p>
              </div>
            ) : (
              <div className="flex flex-col gap-2.5">
                {downloads.map((dl) => (
                  <DownloadCard key={dl.download_id} dl={dl} />
                ))}
              </div>
            )}
            {hasFailed && !hasRunning && (
              <div className="rounded-xl border border-destructive/25 bg-destructive/5 px-4 py-3 text-xs text-destructive/80">
                Fallaron {failedCount} descarga(s). Reintenta o vuelve para cambiar el modelo.
              </div>
            )}
            {hasFailed && !hasRunning && (
              <button onClick={retryFailedDownloads} disabled={retrying} className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl glass-control border border-border/50 text-xs text-foreground/80 hover:border-border/80 hover:bg-card/50 disabled:opacity-60 transition-all">
                {retrying ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
                {retrying ? 'Reintentando...' : 'Reintentar descargas fallidas'}
              </button>
            )}
            {(allSucceeded || downloads.length === 0) && (
              <button onClick={finishSetup} disabled={completing} className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 btn-glow disabled:opacity-50 transition-all duration-200">
                {completing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                {completing ? 'Guardando...' : 'Guardar y continuar'}
              </button>
            )}
            {hasFailed && !hasRunning && (
              <button onClick={() => setStep('token')} className="w-full py-2.5 rounded-xl glass-control border border-border/40 text-xs text-muted-foreground/60 hover:text-foreground hover:border-border/70 transition-all">
                {'<-'} Volver y ajustar seleccion
              </button>
            )}
          </>
        )}

        {step === 'done' && (
          <div className="flex flex-col items-center gap-6 text-center pt-4">
            <div className="w-16 h-16 rounded-2xl bg-success/10 border border-success/25 flex items-center justify-center">
              <Sparkles className="w-8 h-8 text-success/70" />
            </div>
            <div>
              <h2 className="font-display text-xl font-semibold text-foreground/92 tracking-tight">Todo listo</h2>
              <p className="text-xs text-muted-foreground/50 mt-1.5 max-w-xs mx-auto">Diaricat quedo configurado. Podes cambiar estos ajustes en Configuracion.</p>
            </div>
            <div className="w-full space-y-2 text-left glass-panel rounded-xl p-4">
              <ConfigRow label="Transcripcion" value={setupStatus?.whisper_models.find((m) => m.id === selectedWhisper)?.label ?? selectedWhisper} />
              <ConfigRow label="Modelo LLM" value={selectedLlm === 'none' ? 'Sin modelo' : (setupStatus?.llm_models.find((m) => m.id === selectedLlm)?.label ?? selectedLlm)} />
              <ConfigRow label="Diarizacion" value={DIARIZATION_PROFILES.find((p) => p.id === selectedDiarization)?.label ?? selectedDiarization} />
            </div>
            <button onClick={goHome} className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 btn-glow transition-all duration-200">
              Abrir Diaricat
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

const StepHeader = ({ icon, step, title, subtitle }: { icon: ReactNode; step: string; title: string; subtitle: string }) => (
  <div className="space-y-1">
    <div className="flex items-center gap-2">
      {icon}
      <span className="text-[10px] text-muted-foreground/40 uppercase tracking-widest font-medium">{step}</span>
    </div>
    <h2 className="font-display text-base font-semibold text-foreground/92">{title}</h2>
    <p className="text-xs text-muted-foreground/50 leading-relaxed">{subtitle}</p>
  </div>
);

const StepNav = ({ onBack, onNext }: { onBack: () => void; onNext: () => void }) => (
  <div className="flex gap-2 pt-1">
    <button onClick={onBack} className="flex-1 py-2.5 rounded-xl glass-control border border-border/40 text-xs text-muted-foreground/60 hover:text-foreground hover:border-border/70 transition-all">
      {'<-'} Volver
    </button>
    <button onClick={onNext} className="flex-[2] flex items-center justify-center gap-1.5 py-2.5 rounded-xl bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90 btn-glow transition-all duration-200">
      Siguiente
      <ArrowRight className="w-3.5 h-3.5" />
    </button>
  </div>
);

const ConfigRow = ({ label, value }: { label: string; value: string }) => (
  <div className="flex items-center justify-between gap-3 text-xs">
    <span className="text-muted-foreground/50">{label}</span>
    <span className="text-foreground/75 font-medium text-right truncate max-w-[60%]">{value}</span>
  </div>
);

export default SetupWizard;

