import type {
  AppSettings,
  AppSettingsUpdate,
  DeviceMode,
  DownloadStatus,
  ErrorResponse,
  ExportFormat,
  JobStatusResponse,
  ModelInfo,
  ProjectResponse,
  RunPipelineRequest,
  SetupStatus,
  SummaryDocument,
  TranscriptDocument,
} from '@/types/backend';

// Re-export for convenience
export type { ModelInfo, SetupStatus, DownloadStatus };

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '/v1').replace(/\/$/, '');

/** Default request timeout in milliseconds (30 seconds). */
const DEFAULT_TIMEOUT_MS = 30_000;
/** Longer timeout for upload/export operations. */
const LONG_TIMEOUT_MS = 600_000;

const request = async <T>(
  path: string,
  init?: RequestInit & { timeoutMs?: number },
): Promise<T> => {
  const headers = new Headers(init?.headers ?? {});
  if (!(init?.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const timeoutMs = init?.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers,
      signal: controller.signal,
    });

    if (!response.ok) {
      let payload: ErrorResponse | null = null;
      try {
        payload = (await response.json()) as ErrorResponse;
      } catch {
        payload = null;
      }
      const message = payload?.message ?? `HTTP ${response.status}`;
      throw new Error(message);
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error(`Timeout: el servidor no respondio en ${Math.round(timeoutMs / 1000)}s.`);
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
};

export const api = {
  health: () => request<{ status: string }>('/health'),

  uploadFile: (file: File) => {
    const body = new FormData();
    body.append('file', file);
    return request<{ stored_path: string; original_name: string }>('/system/upload', {
      method: 'POST',
      body,
      timeoutMs: LONG_TIMEOUT_MS,
    });
  },

  createProject: (sourcePath: string, deviceMode: DeviceMode, languageHint = 'auto') =>
    request<ProjectResponse>('/projects', {
      method: 'POST',
      body: JSON.stringify({ source_path: sourcePath, device_mode: deviceMode, language_hint: languageHint }),
    }),

  getProject: (projectId: string) => request<ProjectResponse>(`/projects/${projectId}`),

  runPipeline: (projectId: string, payload: RunPipelineRequest) =>
    request<JobStatusResponse>(`/projects/${projectId}/run`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  runCorrection: (projectId: string) =>
    request<JobStatusResponse>(`/projects/${projectId}/correct`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),

  runSummary: (projectId: string) =>
    request<JobStatusResponse>(`/projects/${projectId}/summarize`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),

  getJob: (jobId: string) => request<JobStatusResponse>(`/jobs/${jobId}`),

  cancelJob: (jobId: string) =>
    request<JobStatusResponse>(`/jobs/${jobId}/cancel`, { method: 'POST' }),

  getTranscript: (projectId: string) => request<TranscriptDocument>(`/projects/${projectId}/transcript`),

  getSummary: (projectId: string) => request<SummaryDocument>(`/projects/${projectId}/summary`),

  renameSpeakers: (projectId: string, mapping: Record<string, string>) =>
    request<{ project_id: string; updated_segments: number; mapping: Record<string, string> }>(
      `/projects/${projectId}/speakers/rename`,
      {
        method: 'POST',
        body: JSON.stringify({ mapping }),
      }
    ),

  exportProject: (projectId: string, formats: ExportFormat[], includeTimestamps: boolean) =>
    request<{ project_id: string; artifacts: Record<string, string> }>(`/projects/${projectId}/export`, {
      method: 'POST',
      body: JSON.stringify({ formats, include_timestamps: includeTimestamps }),
      timeoutMs: LONG_TIMEOUT_MS,
    }),

  listArtifacts: (projectId: string) =>
    request<{ project_id: string; pipeline_state: string; artifacts: Record<string, string> }>(
      `/projects/${projectId}/artifacts`
    ),

  openFile: (path: string) =>
    request<{ status: string; path: string }>('/system/open-file', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),

  openFolder: (path: string) =>
    request<{ status: string; path: string }>('/system/open-folder', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),

  getSettings: () => request<AppSettings>('/settings'),

  updateSettings: (payload: AppSettingsUpdate) =>
    request<AppSettings>('/settings', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  // ── Setup wizard ────────────────────────────────────────────────────────────
  getSetupStatus: () => request<SetupStatus>('/setup/status'),

  startDownload: (kind: 'whisper' | 'llm', model_id: string) =>
    request<DownloadStatus>('/setup/download', {
      method: 'POST',
      body: JSON.stringify({ kind, model_id }),
    }),

  pollDownload: (download_id: string) =>
    request<DownloadStatus>(`/setup/downloads/${download_id}`),

  completeSetup: (params: {
    whisper_model?: string;
    llm_model_id?: string;
    hf_token?: string;
    diarization_profile?: string;
  }) => {
    const qs = new URLSearchParams();
    if (params.whisper_model) qs.set('whisper_model', params.whisper_model);
    if (params.llm_model_id) qs.set('llm_model_id', params.llm_model_id);
    if (params.hf_token !== undefined) qs.set('hf_token', params.hf_token);
    if (params.diarization_profile) qs.set('diarization_profile', params.diarization_profile);
    return request<AppSettings>(`/setup/complete?${qs.toString()}`, { method: 'POST' });
  },
};
