"""API request/response contracts."""

from __future__ import annotations

from pydantic import BaseModel, Field

from diaricat.models.domain import DeviceMode, ExportFormat, JobStatus, PipelineState


class ProjectCreateRequest(BaseModel):
    source_path: str
    device_mode: DeviceMode = DeviceMode.AUTO
    language_hint: str = "auto"


class ProjectResponse(BaseModel):
    id: str
    source_path: str
    device_mode: DeviceMode
    language_hint: str
    pipeline_state: PipelineState
    error_code: str | None = None
    error_detail: str | None = None
    artifacts: dict[str, str]


class RunPipelineRequest(BaseModel):
    run_correction: bool = True
    run_summary: bool = True


class RenameSpeakersRequest(BaseModel):
    mapping: dict[str, str] = Field(default_factory=dict)


class ExportRequest(BaseModel):
    formats: list[ExportFormat] = Field(
        default_factory=lambda: [
            ExportFormat.JSON,
            ExportFormat.MD,
            ExportFormat.TXT,
            ExportFormat.PDF,
            ExportFormat.DOCX,
        ]
    )
    include_timestamps: bool = True


class OpenPathRequest(BaseModel):
    path: str


class JobStatusResponse(BaseModel):
    job_id: str
    project_id: str
    stage: str
    progress: int
    status: JobStatus
    error_code: str | None = None
    error_detail: str | None = None
    failure_component: str | None = None
    error_hint: str | None = None
    attempt: int | None = None
    result: dict[str, str] | dict[str, object] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    details: str | None = None
    failure_component: str | None = None
    error_hint: str | None = None
    attempt: int | None = None


class SystemSpecsResponse(BaseModel):
    ram_gb: float
    cpu_cores: int
    has_gpu: bool
    gpu_usable: bool = False
    gpu_name: str | None = None
    gpu_vram_gb: float = 0.0


class ModelInfo(BaseModel):
    id: str
    label: str
    size_mb: int
    quality: int           # 0-5
    speed: int             # 0-4 (only whisper)
    min_ram_gb: float
    description: str
    is_cached: bool
    compatible: bool       # fits within detected system RAM


class ModelRecommendation(BaseModel):
    whisper_id: str
    llm_id: str


class SetupStatusResponse(BaseModel):
    setup_done: bool
    specs: SystemSpecsResponse
    whisper_models: list[ModelInfo]
    llm_models: list[ModelInfo]
    recommendation: ModelRecommendation


class DownloadRequest(BaseModel):
    kind: str          # "whisper" | "llm"
    model_id: str


class DownloadStatusResponse(BaseModel):
    download_id: str
    status: str        # "running" | "done" | "failed"
    downloaded_bytes: int = 0
    total_bytes: int = 0
    progress_pct: float = 0.0
    error: str | None = None


class AppSettingsResponse(BaseModel):
    whisper_model: str
    whisper_compute_type: str
    hf_token: str
    llama_model_path: str
    llama_n_ctx: int
    llama_n_threads: int
    whisper_chunk_seconds: int
    whisper_beam_size: int
    whisper_cpu_threads: int
    summary_chunk_chars: int
    diarization_profile: str
    workspace_dir: str
    fullscreen_on_maximize: bool = False
    llm_available: bool = False   # True if the .gguf file exists on disk


class AppSettingsUpdateRequest(BaseModel):
    whisper_model: str | None = None
    whisper_compute_type: str | None = None
    hf_token: str | None = None
    llama_model_path: str | None = None
    llama_n_ctx: int | None = None
    llama_n_threads: int | None = None
    whisper_chunk_seconds: int | None = None
    whisper_beam_size: int | None = None
    whisper_cpu_threads: int | None = None
    summary_chunk_chars: int | None = None
    diarization_profile: str | None = None
    workspace_dir: str | None = None
    fullscreen_on_maximize: bool | None = None


class DiagnosticsComponentStatus(BaseModel):
    ok: bool
    version: str | None = None
    error_hint: str | None = None


class SystemDiagnosticsResponse(BaseModel):
    components: dict[str, DiagnosticsComponentStatus]
