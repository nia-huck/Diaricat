export type DeviceMode = 'auto' | 'cpu' | 'gpu';
export type JobStatus = 'queued' | 'running' | 'done' | 'failed';
export type ExportFormat = 'json' | 'md' | 'txt' | 'pdf' | 'docx';

export interface ProjectResponse {
  id: string;
  source_path: string;
  device_mode: DeviceMode;
  language_hint: string;
  pipeline_state: string;
  error_code?: string | null;
  error_detail?: string | null;
  artifacts: Record<string, string>;
}

export interface RunPipelineRequest {
  run_correction: boolean;
  run_summary: boolean;
}

export interface JobStatusResponse {
  job_id: string;
  project_id: string;
  stage: string;
  progress: number;
  status: JobStatus;
  error_code?: string | null;
  error_detail?: string | null;
  result?: Record<string, unknown>;
}

export interface TranscriptSegment {
  start: number;
  end: number;
  speaker_id: string;
  speaker_name?: string | null;
  text_raw: string;
  text_corrected?: string | null;
}

export interface SpeakerProfile {
  speaker_id: string;
  custom_name?: string | null;
  color_ui: string;
}

export interface TranscriptDocument {
  segments: TranscriptSegment[];
  full_text_raw: string;
  full_text_corrected?: string | null;
  quality_metadata: Record<string, unknown>;
  speaker_profiles: SpeakerProfile[];
}

export interface SummaryDocument {
  overview: string;
  key_points: string[];
  decisions: string[];
  topics: string[];
}

export interface ErrorResponse {
  error_code: string;
  message: string;
  details?: string | null;
}

// ── Setup wizard types ───────────────────────────────────────────────────────

export interface SystemSpecs {
  ram_gb: number;
  cpu_cores: number;
  has_gpu: boolean;
  gpu_usable: boolean;
  gpu_name: string | null;
  gpu_vram_gb: number;
}

export interface ModelInfo {
  id: string;
  label: string;
  size_mb: number;
  quality: number;    // 0-5
  speed: number;      // 0-4
  min_ram_gb: number;
  description: string;
  is_cached: boolean;
  compatible: boolean;
}

export interface ModelRecommendation {
  whisper_id: string;
  llm_id: string;
}

export interface SetupStatus {
  setup_done: boolean;
  specs: SystemSpecs;
  whisper_models: ModelInfo[];
  llm_models: ModelInfo[];
  recommendation: ModelRecommendation;
}

export interface DownloadStatus {
  download_id: string;
  status: 'running' | 'done' | 'failed';
  downloaded_bytes: number;
  total_bytes: number;
  progress_pct: number;
  error: string | null;
}

// ── Settings types ───────────────────────────────────────────────────────────

export interface AppSettings {
  whisper_model: string;
  whisper_compute_type: string;
  hf_token: string;
  llama_model_path: string;
  llama_n_ctx: number;
  llama_n_threads: number;
  diarization_profile: string;
  workspace_dir: string;
  fullscreen_on_maximize: boolean;
  llm_available: boolean;
}

export type AppSettingsUpdate = Partial<AppSettings>;
