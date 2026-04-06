import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { api } from '@/lib/api';
import { translate, getStoredLang } from '@/lib/i18n';
import type {
  AppSettings,
  AppSettingsUpdate,
  DeviceMode,
  ExportFormat,
  JobStatus,
  SummaryDocument,
  TranscriptDocument,
  TranscriptSegment,
} from '@/types/backend';

export type AppScreen = 'home' | 'processing' | 'results' | 'export' | 'settings' | 'setup';

interface AppState {
  screen: AppScreen;
  setScreen: (screen: AppScreen) => void;
  fileName: string;
  filePath: string;
  computeMode: DeviceMode;
  setComputeMode: (mode: DeviceMode) => void;
  projectId: string | null;
  jobId: string | null;
  pipelineStage: string;
  pipelineProgress: number;
  runCorrectionEnabled: boolean;
  runSummaryEnabled: boolean;
  jobStatus: JobStatus | null;
  logs: string[];
  errorMessage: string | null;
  isBusy: boolean;
  speakers: Record<string, string>;
  corrected: boolean;
  summaryGenerated: boolean;
  viewMode: 'original' | 'corrected';
  setViewMode: (mode: 'original' | 'corrected') => void;
  transcript: TranscriptDocument | null;
  transcriptSegments: TranscriptSegment[];
  summary: SummaryDocument | null;
  artifacts: Record<string, string>;
  settings: AppSettings | null;
  startPipeline: (sourcePath: string) => Promise<void>;
  cancelProcessing: () => void;
  runCorrection: () => Promise<void>;
  runSummary: () => Promise<void>;
  renameSpeaker: (speakerId: string, customName: string) => Promise<void>;
  exportResults: (formats: ExportFormat[], includeTimestamps: boolean) => Promise<Record<string, string>>;
  refreshProjectData: (forcedProjectId?: string) => Promise<void>;
  saveSettings: (updates: AppSettingsUpdate) => Promise<void>;
  refreshSettings: () => Promise<void>;
  clearError: () => void;
  startNewProject: () => void;
}

const AppContext = createContext<AppState | null>(null);

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const deriveFileName = (sourcePath: string): string => {
  const normalized = sourcePath.replace(/\\/g, '/');
  const parts = normalized.split('/');
  return parts[parts.length - 1] || sourcePath;
};

const stageLabelKey = (stage: string): string => {
  const keyMap: Record<string, string> = {
    queued: 'stage.queued',
    running: 'stage.running',
    validating: 'stage.validating',
    audio: 'stage.audio',
    transcription: 'stage.transcription',
    diarization: 'stage.diarization',
    merge: 'stage.merge',
    correction: 'stage.correction',
    summary: 'stage.summary',
    done: 'stage.done',
    failed: 'stage.failed',
    interrupted: 'stage.interrupted',
  };
  return keyMap[stage] ?? stage;
};

const buildSpeakerMap = (transcript: TranscriptDocument | null): Record<string, string> => {
  if (!transcript) {
    return {};
  }

  const mapping: Record<string, string> = {};

  transcript.speaker_profiles.forEach((profile) => {
    mapping[profile.speaker_id] = profile.custom_name || profile.speaker_id;
  });

  transcript.segments.forEach((segment) => {
    if (!mapping[segment.speaker_id]) {
      mapping[segment.speaker_id] = segment.speaker_name || segment.speaker_id;
    }
  });

  return mapping;
};

export const useAppState = (): AppState => {
  const ctx = useContext(AppContext);
  if (!ctx) {
    throw new Error('useAppState must be used within AppProvider');
  }
  return ctx;
};

export const AppProvider = ({ children }: { children: ReactNode }) => {
  const [screen, setScreen] = useState<AppScreen>('home');
  const [filePath, setFilePath] = useState('');
  const [fileName, setFileName] = useState('');
  const [computeMode, setComputeMode] = useState<DeviceMode>('auto');
  const [projectId, setProjectId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [pipelineStage, setPipelineStage] = useState('queued');
  const [pipelineProgress, setPipelineProgress] = useState(0);
  const [runCorrectionEnabled, setRunCorrectionEnabled] = useState(false);
  const [runSummaryEnabled, setRunSummaryEnabled] = useState(false);
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [transcript, setTranscript] = useState<TranscriptDocument | null>(null);
  const [summary, setSummary] = useState<SummaryDocument | null>(null);
  const [speakers, setSpeakers] = useState<Record<string, string>>({});
  const [viewMode, setViewMode] = useState<'original' | 'corrected'>('original');
  const [artifacts, setArtifacts] = useState<Record<string, string>>({});
  const [settings, setSettings] = useState<AppSettings | null>(null);

  const pollTokenRef = useRef(0);
  const lastStageRef = useRef('');

  const corrected = useMemo(
    () => Boolean(transcript?.segments.some((segment) => (segment.text_corrected ?? '').trim().length > 0)),
    [transcript]
  );
  const summaryGenerated = useMemo(
    () => Boolean(summary && (summary.overview || summary.key_points.length || summary.decisions.length || summary.topics.length)),
    [summary]
  );

  const appendLog = useCallback((message: string) => {
    setLogs((previous) => {
      const next = [...previous, message];
      return next.slice(Math.max(0, next.length - 120));
    });
  }, []);

  const clearError = useCallback(() => {
    setErrorMessage(null);
  }, []);

  const startNewProject = useCallback(() => {
    pollTokenRef.current += 1;
    setScreen('home');
    setFilePath('');
    setFileName('');
    setProjectId(null);
    setJobId(null);
    setPipelineStage('queued');
    setPipelineProgress(0);
    setRunCorrectionEnabled(false);
    setRunSummaryEnabled(false);
    setJobStatus(null);
    setLogs([]);
    setErrorMessage(null);
    setIsBusy(false);
    setTranscript(null);
    setSummary(null);
    setSpeakers({});
    setViewMode('original');
    setArtifacts({});
    lastStageRef.current = '';
  }, []);

  const refreshProjectData = useCallback(
    async (forcedProjectId?: string): Promise<void> => {
      const targetProjectId = forcedProjectId || projectId;
      if (!targetProjectId) {
        return;
      }

      const project = await api.getProject(targetProjectId);
      setArtifacts(project.artifacts || {});

      try {
        const transcriptDoc = await api.getTranscript(targetProjectId);
        setTranscript(transcriptDoc);
        setSpeakers(buildSpeakerMap(transcriptDoc));
      } catch {
        setTranscript(null);
        setSpeakers({});
      }

      try {
        const summaryDoc = await api.getSummary(targetProjectId);
        setSummary(summaryDoc);
      } catch {
        setSummary(null);
      }
    },
    [projectId]
  );

  const monitorJob = useCallback(
    async (incomingJobId: string, targetProjectId: string, successScreen: AppScreen | null) => {
      pollTokenRef.current += 1;
      const token = pollTokenRef.current;
      setJobId(incomingJobId);
      setIsBusy(true);
      setErrorMessage(null);

      let consecutiveErrors = 0;
      const MAX_CONSECUTIVE_ERRORS = 5;

      try {
        while (pollTokenRef.current === token) {
          let job: typeof undefined | Awaited<ReturnType<typeof api.getJob>>;
          try {
            job = await api.getJob(incomingJobId);
            consecutiveErrors = 0;
          } catch {
            consecutiveErrors += 1;
            if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
              setErrorMessage('Se perdio la conexion con el backend despues de varios intentos.');
              appendLog('Error: conexion con el backend perdida.');
              return;
            }
            // Exponential backoff on transient failures
            await sleep(Math.min(1000 * Math.pow(2, consecutiveErrors - 1), 8000));
            continue;
          }
          if (pollTokenRef.current !== token) break;

          setJobStatus(job.status);
          setPipelineStage(job.stage);
          setPipelineProgress(job.progress);

          if (job.stage !== lastStageRef.current) {
            lastStageRef.current = job.stage;
            const label = translate(stageLabelKey(job.stage), getStoredLang());
            appendLog(`${label} (${job.progress}%)`);
          }

          if (job.status === 'done') {
            setPipelineProgress(100);
            setPipelineStage('done');
            appendLog('Pipeline completado. Cargando resultados...');
            await refreshProjectData(targetProjectId);
            if (successScreen) {
              setScreen(successScreen);
            }
            return;
          }

          if (job.status === 'failed') {
            const message = job.error_detail || job.error_code || 'Fallo en el procesamiento.';
            setErrorMessage(message);
            setPipelineStage('failed');
            appendLog(`Error: ${message}`);
            return;
          }

          await sleep(1500);
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Error de conexion con el backend.';
        setErrorMessage(message);
        appendLog(`Error de polling: ${message}`);
      } finally {
        setIsBusy(false);
      }
    },
    [appendLog, refreshProjectData]
  );

  const startPipeline = useCallback(
    async (sourcePath: string): Promise<void> => {
      const normalizedPath = sourcePath.trim();
      if (!normalizedPath) {
        setErrorMessage('Debes ingresar la ruta local del archivo.');
        return;
      }

      pollTokenRef.current += 1;
      setErrorMessage(null);
      setLogs([]);
      setPipelineStage('queued');
      setPipelineProgress(0);
      setSummary(null);
      setTranscript(null);
      setSpeakers({});
      setArtifacts({});
      setViewMode('original');

      setFilePath(normalizedPath);
      setFileName(deriveFileName(normalizedPath));

      try {
        appendLog('Creando proyecto...');
        const langHint = getStoredLang() === 'en' ? 'en' : 'es';
        const project = await api.createProject(normalizedPath, computeMode, langHint);
        setProjectId(project.id);
        setJobStatus('queued');
        setScreen('processing');

        const llmReady = settings?.llm_available ?? false;
        const runCorrection = true;
        const runSummary = true;
        setRunCorrectionEnabled(runCorrection);
        setRunSummaryEnabled(runSummary);
        appendLog('Enviando pipeline a ejecucion...');
        if (!llmReady) {
          appendLog('LLM local no disponible: se usara modo fallback para correccion/resumen.');
        }
        const job = await api.runPipeline(project.id, { run_correction: runCorrection, run_summary: runSummary });
        await monitorJob(job.job_id, project.id, 'results');
      } catch (error) {
        const message = error instanceof Error ? error.message : 'No se pudo iniciar el pipeline.';
        setErrorMessage(message);
        appendLog(`Error al iniciar: ${message}`);
        setIsBusy(false);
        setScreen('home');
      }
    },
    [appendLog, computeMode, monitorJob, settings?.llm_available]
  );

  const runCorrection = useCallback(async (): Promise<void> => {
    if (!projectId) {
      setErrorMessage('No hay proyecto activo para corregir.');
      return;
    }
    try {
      setErrorMessage(null);
      appendLog('Solicitando correccion de transcripcion...');
      const job = await api.runCorrection(projectId);
      await monitorJob(job.job_id, projectId, null);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'No se pudo ejecutar la correccion.';
      setErrorMessage(message);
      appendLog(`Error en correccion: ${message}`);
      setIsBusy(false);
    }
  }, [appendLog, monitorJob, projectId]);

  const runSummary = useCallback(async (): Promise<void> => {
    if (!projectId) {
      setErrorMessage('No hay proyecto activo para resumir.');
      return;
    }
    try {
      setErrorMessage(null);
      appendLog('Solicitando generacion de resumen...');
      const job = await api.runSummary(projectId);
      await monitorJob(job.job_id, projectId, null);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'No se pudo ejecutar el resumen.';
      setErrorMessage(message);
      appendLog(`Error en resumen: ${message}`);
      setIsBusy(false);
    }
  }, [appendLog, monitorJob, projectId]);

  const renameSpeaker = useCallback(
    async (speakerId: string, customName: string): Promise<void> => {
      if (!projectId) {
        setErrorMessage('No hay proyecto activo para renombrar speakers.');
        return;
      }

      const trimmed = customName.trim();
      if (!trimmed) {
        return;
      }

      // Build the mapping from current state synchronously, then update UI optimistically.
      const updatedMapping: Record<string, string> = { ...speakers, [speakerId]: trimmed };
      setSpeakers(updatedMapping);

      try {
        setErrorMessage(null);
        await api.renameSpeakers(projectId, updatedMapping);
        await refreshProjectData(projectId);
      } catch (error) {
        const message = error instanceof Error ? error.message : 'No se pudo guardar el nombre del speaker.';
        setErrorMessage(message);
        // Revert optimistic update on failure
        await refreshProjectData(projectId);
      }
    },
    [projectId, refreshProjectData, speakers]
  );

  const exportResults = useCallback(
    async (formats: ExportFormat[], includeTimestamps: boolean): Promise<Record<string, string>> => {
      if (!projectId) {
        throw new Error('No hay proyecto activo para exportar.');
      }

      const response = await api.exportProject(projectId, formats, includeTimestamps);
      setArtifacts(response.artifacts);
      return response.artifacts;
    },
    [projectId]
  );

  const cancelProcessing = useCallback(() => {
    pollTokenRef.current += 1;
    if (jobId) {
      api.cancelJob(jobId).catch(() => {});
    }
    setIsBusy(false);
    setScreen('home');
  }, [jobId]);

  const saveSettings = useCallback(async (updates: AppSettingsUpdate): Promise<void> => {
    const updated = await api.updateSettings(updates);
    setSettings(updated);
  }, []);

  const refreshSettings = useCallback(async (): Promise<void> => {
    try {
      const updated = await api.getSettings();
      setSettings(updated);
    } catch {
      // ignore transient errors
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const MAX_RETRIES = 10;
    const RETRY_DELAY_MS = 1500;

    const connectToBackend = async () => {
      for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
        if (cancelled) return;
        try {
          await api.health();
          // Backend is up — load settings and setup status
          try {
            const s = await api.getSettings();
            if (!cancelled) setSettings(s);
          } catch { /* non-critical */ }
          try {
            const status = await api.getSetupStatus();
            if (!cancelled && !status.setup_done) setScreen('setup');
          } catch { /* non-critical */ }
          return;
        } catch {
          if (attempt < MAX_RETRIES - 1) {
            await sleep(RETRY_DELAY_MS);
          }
        }
      }
      if (!cancelled) {
        setErrorMessage('No se pudo conectar con el backend. Verifica que el servidor este ejecutandose.');
      }
    };
    void connectToBackend();
    return () => { cancelled = true; };
  }, []);

  const value = useMemo<AppState>(
    () => ({
      screen,
      setScreen,
      fileName,
      filePath,
      computeMode,
      setComputeMode,
      projectId,
      jobId,
      pipelineStage,
      pipelineProgress,
      runCorrectionEnabled,
      runSummaryEnabled,
      jobStatus,
      logs,
      errorMessage,
      isBusy,
      speakers,
      corrected,
      summaryGenerated,
      viewMode,
      setViewMode,
      transcript,
      transcriptSegments: transcript?.segments ?? [],
      summary,
      artifacts,
      settings,
      startPipeline,
      cancelProcessing,
      runCorrection,
      runSummary,
      renameSpeaker,
      exportResults,
      refreshProjectData,
      saveSettings,
      refreshSettings,
      clearError,
      startNewProject,
    }),
    [
      artifacts,
      cancelProcessing,
      clearError,
      computeMode,
      corrected,
      errorMessage,
      exportResults,
      fileName,
      filePath,
      isBusy,
      jobId,
      jobStatus,
      logs,
      pipelineProgress,
      pipelineStage,
      projectId,
      runCorrectionEnabled,
      runSummaryEnabled,
      refreshProjectData,
      refreshSettings,
      renameSpeaker,
      runCorrection,
      runSummary,
      saveSettings,
      screen,
      settings,
      speakers,
      startNewProject,
      startPipeline,
      summary,
      summaryGenerated,
      transcript,
      viewMode,
    ]
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
};
