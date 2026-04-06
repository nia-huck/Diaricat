"""FastAPI application and HTTP routes."""

from __future__ import annotations

import logging
import os
import subprocess
import shutil
import sys
import threading
import uuid
import ipaddress
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, NoReturn

import uvicorn
from fastapi import APIRouter, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from diaricat.bootstrap import AppContext, get_context
from diaricat.errors import DiaricatError, ErrorCode
from diaricat.models.api import (
    AppSettingsResponse,
    AppSettingsUpdateRequest,
    DownloadRequest,
    DownloadStatusResponse,
    ErrorResponse,
    ExportRequest,
    JobStatusResponse,
    ModelInfo,
    ModelRecommendation,
    OpenPathRequest,
    ProjectCreateRequest,
    ProjectResponse,
    RenameSpeakersRequest,
    RunPipelineRequest,
    SetupStatusResponse,
    SystemDiagnosticsResponse,
    SystemSpecsResponse,
)
from diaricat.services import setup_service
from diaricat.settings import save_settings
from diaricat.models.domain import ExportFormat, Project, SummaryDocument, TranscriptDocument
from diaricat.utils.validation import ALLOWED_EXTENSIONS
from diaricat.utils.logging import SESSION_ID, get_security_logger

_sec_log = get_security_logger()
_api_log = logging.getLogger("diaricat.api")

MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB

# System specs are expensive to detect (torch.cuda). Cache for the process lifetime.
_cached_system_specs: dict | None = None
_specs_lock = threading.Lock()


def _get_system_specs() -> dict:
    global _cached_system_specs
    if _cached_system_specs is not None:
        return _cached_system_specs
    with _specs_lock:
        if _cached_system_specs is None:
            _cached_system_specs = setup_service.detect_system()
    return _cached_system_specs


def _settings_to_response(ctx: AppContext) -> AppSettingsResponse:
    s = ctx.settings.services
    llm_path = Path(str(s.llama_model_path))
    if not llm_path.is_absolute():
        llm_path = ctx.settings.app.workspace_dir / llm_path
    return AppSettingsResponse(
        whisper_model=s.whisper_model,
        whisper_compute_type=s.whisper_compute_type,
        hf_token=s.hf_token,
        llama_model_path=str(s.llama_model_path),
        llama_n_ctx=s.llama_n_ctx,
        llama_n_threads=s.llama_n_threads,
        whisper_chunk_seconds=s.whisper_chunk_seconds,
        whisper_beam_size=s.whisper_beam_size,
        whisper_cpu_threads=s.whisper_cpu_threads,
        summary_chunk_chars=s.summary_chunk_chars,
        diarization_profile=s.diarization_profile,
        workspace_dir=str(ctx.settings.app.workspace_dir),
        fullscreen_on_maximize=ctx.settings.app.fullscreen_on_maximize,
        llm_available=setup_service.is_llm_present(llm_path),
    )


def _project_to_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        source_path=project.source_path,
        device_mode=project.device_mode,
        language_hint=project.language_hint,
        pipeline_state=project.pipeline_state,
        error_code=project.error_code,
        error_detail=project.error_detail,
        artifacts=project.artifacts,
    )


def _job_to_response(job) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=job.job_id,
        project_id=job.project_id,
        stage=job.stage,
        progress=job.progress,
        status=job.status,
        error_code=job.error_code,
        error_detail=job.error_detail,
        failure_component=job.failure_component,
        error_hint=job.error_hint,
        attempt=job.attempt,
        result=job.result,
    )


def _raise_http(exc: DiaricatError, status_code: int = 400) -> NoReturn:
    raise HTTPException(status_code=status_code, detail=ErrorResponse(**exc.to_dict()).model_dump())


def _resolve_frontend_dist() -> Path | None:
    env_path = os.environ.get("DIARICAT_FRONTEND_DIST", "").strip()
    if env_path:
        candidate = Path(env_path)
        if candidate.exists() and (candidate / "index.html").exists():
            return candidate

    project_root = Path(__file__).resolve().parents[3]
    bundled_root = Path(getattr(sys, "_MEIPASS", project_root))

    candidates = [
        bundled_root / "frontend_dist",
        project_root / "frontend" / "dist",
    ]
    for candidate in candidates:
        if candidate.exists() and (candidate / "index.html").exists():
            return candidate
    return None


def _resolve_local_path(raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (Path.cwd() / candidate).resolve()


def _assert_path_within_workspace(target: Path, ctx: AppContext) -> None:
    """Ensure target path is within workspace or temp directories (path-safe)."""
    workspace = ctx.settings.app.workspace_dir.resolve()
    temp = ctx.settings.app.temp_dir.resolve()
    resolved = target.resolve()
    # Use is_relative_to (Python 3.9+) to avoid prefix-collision attacks
    # e.g. workspace=/tmp/ws, target=/tmp/ws2/evil must be rejected.
    within = (
        _is_relative_to(resolved, workspace) or _is_relative_to(resolved, temp)
    )
    if not within:
        _sec_log.warning(
            "path_traversal_attempt path=%s workspace=%s", resolved, workspace
        )
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "FORBIDDEN",
                "message": "Path is outside the allowed workspace directory.",
                "details": None,
            },
        )


def _is_relative_to(path: Path, parent: Path) -> bool:
    """Path.is_relative_to backport for Python < 3.9."""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _reveal_in_windows_explorer(target: Path) -> None:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    resolved = target.resolve()
    subprocess.Popen(
        ["explorer", "/select,", str(resolved)],
        creationflags=creationflags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def create_app(context: AppContext | None = None) -> FastAPI:
    ctx = context or get_context()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        ctx.jobs.start()
        yield
        ctx.jobs.stop()

    app = FastAPI(
        title="Diaricat API",
        version="1.0.0",
        description="Local private transcription backend for Lovable UI integration.",
        lifespan=lifespan,
    )
    # All origins are localhost-only — this is a local-only private application.
    # Dev server ports (5173, 4173, 8080) are included for development workflow.
    _cors_origins = [
        "http://127.0.0.1:8765",
        "http://localhost:8765",
        "http://127.0.0.1:8080",
        "http://localhost:8080",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def dns_rebinding_guard(request: Request, call_next):
        host_header = (request.headers.get("host") or "").split(":")[0].lower()
        allowed_hosts = {"127.0.0.1", "localhost", ""}
        if host_header not in allowed_hosts:
            _sec_log.warning(
                "dns_rebind_attempt host=%r remote=%s path=%s",
                host_header,
                request.client.host if request.client else "unknown",
                request.url.path,
            )
            return JSONResponse(
                status_code=403,
                content={"error_code": "FORBIDDEN", "message": "Invalid Host header.", "details": None},
            )

        client_host = (request.client.host if request.client else "").strip().lower()
        if client_host:
            is_loopback = False
            try:
                is_loopback = ipaddress.ip_address(client_host).is_loopback
            except ValueError:
                is_loopback = client_host in {"localhost", "testclient"}
            if not is_loopback:
                _sec_log.warning(
                    "non_loopback_client host=%r remote=%s path=%s",
                    host_header,
                    client_host,
                    request.url.path,
                )
                return JSONResponse(
                    status_code=403,
                    content={"error_code": "FORBIDDEN", "message": "Client address not allowed.", "details": None},
                )
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Session-Id"] = SESSION_ID
        return response

    @app.middleware("http")
    async def request_logger(request: Request, call_next):
        import time as _time
        start = _time.monotonic()
        response = await call_next(request)
        elapsed_ms = int((_time.monotonic() - start) * 1000)
        # Log non-health requests at DEBUG to avoid noise
        path = request.url.path
        level = logging.DEBUG if path.endswith("/health") else logging.INFO
        _api_log.log(
            level,
            "%s %s -> %s (%dms)",
            request.method,
            path,
            response.status_code,
            elapsed_ms,
        )
        return response

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and {"error_code", "message"}.issubset(exc.detail.keys()):
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_code": "HTTP_ERROR",
                "message": str(exc.detail),
                "details": None,
            },
        )

    router = APIRouter(prefix="/v1", tags=["v1"])
    _api_log.info("API ready session=%s", SESSION_ID)

    @router.get("/health", response_model=dict[str, str])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/version", response_model=dict[str, str])
    def version() -> dict[str, str]:
        import platform as _plat
        return {
            "app": "diaricat",
            "version": "1.0.0",
            "session": SESSION_ID,
            "python": _plat.python_version(),
            "platform": _plat.system(),
        }

    @router.get("/system/diagnostics", response_model=SystemDiagnosticsResponse)
    def get_diagnostics() -> SystemDiagnosticsResponse:
        raw = setup_service.runtime_diagnostics()
        failed = [name for name, status in raw.items() if not status.get("ok", False)]
        _api_log.info(
            "Runtime diagnostics requested.",
            extra={
                "ctx_component_count": len(raw),
                "ctx_failed_components": failed,
            },
        )
        return SystemDiagnosticsResponse(components=raw)

    # ── Setup endpoints ────────────────────────────────────────────────────────

    @router.get("/setup/status", response_model=SetupStatusResponse)
    def get_setup_status() -> SetupStatusResponse:
        specs_raw = _get_system_specs()
        specs = SystemSpecsResponse(**specs_raw)
        rec_ids = setup_service.recommend_models(specs.ram_gb, specs.gpu_vram_gb, specs.gpu_usable)
        llm_dest = ctx.settings.app.workspace_dir / "models"

        whisper_models = [
            ModelInfo(
                id=m["id"],
                label=m["label"],
                size_mb=m["size_mb"],
                quality=m["quality"],
                speed=m.get("speed", 0),
                min_ram_gb=m["min_ram_gb"],
                description=m["description"],
                is_cached=setup_service.is_whisper_cached(m["id"]),
                compatible=specs.ram_gb >= m["min_ram_gb"]
                or (specs.gpu_usable and specs.gpu_vram_gb >= m["min_ram_gb"] / 1.5),
            )
            for m in setup_service.WHISPER_MODELS
        ]

        llm_models = [
            ModelInfo(
                id=m["id"],
                label=m["label"],
                size_mb=m["size_mb"],
                quality=m["quality"],
                speed=0,
                min_ram_gb=m["min_ram_gb"],
                description=m["description"],
                is_cached=m["filename"] is not None
                and setup_service.find_existing_llm_path(m, llm_dest) is not None,
                compatible=m["id"] == "none" or specs.ram_gb >= m["min_ram_gb"],
            )
            for m in setup_service.LLM_MODELS
        ]

        return SetupStatusResponse(
            setup_done=ctx.settings.app.setup_done,
            specs=specs,
            whisper_models=whisper_models,
            llm_models=llm_models,
            recommendation=ModelRecommendation(
                whisper_id=rec_ids["whisper"],
                llm_id=rec_ids["llm"],
            ),
        )

    @router.post("/setup/download", response_model=DownloadStatusResponse)
    def start_setup_download(payload: DownloadRequest) -> DownloadStatusResponse:
        hf_token = ctx.settings.services.hf_token or None
        llm_dest = ctx.settings.app.workspace_dir / "models"

        try:
            if payload.kind == "whisper":
                download_id = setup_service.start_whisper_download(payload.model_id, hf_token)
            elif payload.kind == "llm":
                download_id = setup_service.start_llm_download(payload.model_id, llm_dest, hf_token)
            else:
                raise HTTPException(
                    status_code=400,
                    detail={"error_code": "VALIDATION_ERROR", "message": f"Unknown kind: {payload.kind!r}", "details": None},
                )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"error_code": "VALIDATION_ERROR", "message": str(exc), "details": None},
            ) from exc

        return DownloadStatusResponse(download_id=download_id, status="running")

    @router.get("/setup/downloads/{download_id}", response_model=DownloadStatusResponse)
    def get_download_status(download_id: str) -> DownloadStatusResponse:
        status = setup_service.get_download_status(download_id)
        if status is None:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "NOT_FOUND", "message": "Download not found.", "details": None},
            )
        total = status.get("total_bytes", 0)
        done = status.get("downloaded_bytes", 0)
        pct = round((done / total * 100) if total > 0 else 0.0, 1)
        return DownloadStatusResponse(
            download_id=download_id,
            status=status["status"],
            downloaded_bytes=done,
            total_bytes=total,
            progress_pct=pct,
            error=status.get("error"),
        )

    @router.post("/setup/complete", response_model=AppSettingsResponse)
    def complete_setup(
        whisper_model: str | None = None,
        llm_model_id: str | None = None,
        hf_token: str | None = None,
        diarization_profile: str | None = None,
    ) -> AppSettingsResponse:
        """Mark setup as done and persist chosen model settings."""
        ctx.settings.app.setup_done = True
        s = ctx.settings.services

        if whisper_model:
            s.whisper_model = whisper_model
        if hf_token is not None:
            s.hf_token = hf_token
        if diarization_profile:
            s.diarization_profile = diarization_profile

        # Map LLM model id to a path
        if llm_model_id and llm_model_id != "none":
            llm_info = setup_service.get_llm_model(llm_model_id)
            if llm_info and llm_info.get("filename"):
                llm_dest = ctx.settings.app.workspace_dir / "models"
                existing = setup_service.find_existing_llm_path(llm_info, llm_dest)
                if existing is not None:
                    s.llama_model_path = Path("models") / existing.name
                else:
                    s.llama_model_path = Path("models") / llm_info["filename"]

        save_settings(ctx.settings)
        return _settings_to_response(ctx)

    @router.post("/system/upload", response_model=dict[str, str])
    def upload_media(file: UploadFile = File(...)) -> dict[str, str]:
        filename = (file.filename or "").strip()
        suffix = Path(filename).suffix.lower()
        if not suffix or suffix not in ALLOWED_EXTENSIONS:
            allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
            raise HTTPException(
                status_code=400,
                detail={
                    "error_code": "VALIDATION_ERROR",
                    "message": f"Unsupported file extension '{suffix or 'unknown'}'.",
                    "details": f"Allowed: {allowed}",
                },
            )

        uploads_dir = ctx.settings.app.workspace_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}{suffix}"
        stored_path = uploads_dir / stored_name

        bytes_written = 0
        with stored_path.open("wb") as target:
            while True:
                chunk = file.file.read(1024 * 1024)  # 1 MB chunks
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > MAX_UPLOAD_BYTES:
                    target.close()
                    stored_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail={
                            "error_code": "VALIDATION_ERROR",
                            "message": f"File exceeds maximum upload size ({MAX_UPLOAD_BYTES // (1024**3)} GB).",
                            "details": None,
                        },
                    )
                target.write(chunk)

        return {
            "stored_path": str(stored_path),
            "original_name": filename,
        }

    @router.post("/system/open-file", response_model=dict[str, str])
    def open_file(payload: OpenPathRequest) -> dict[str, str]:
        target = _resolve_local_path(payload.path)
        _assert_path_within_workspace(target, ctx)
        if not target.exists() or not target.is_file():
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": "NOT_FOUND",
                    "message": "File not found.",
                    "details": str(target),
                },
            )
        try:
            _reveal_in_windows_explorer(target)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "error_code": "OPEN_FILE_ERROR",
                    "message": "Could not open file with the system shell.",
                    "details": str(exc),
                },
            ) from exc
        return {"status": "ok", "path": str(target)}

    @router.post("/system/open-folder", response_model=dict[str, str])
    def open_folder(payload: OpenPathRequest) -> dict[str, str]:
        target = _resolve_local_path(payload.path)
        _assert_path_within_workspace(target, ctx)
        if not target.exists():
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": "NOT_FOUND",
                    "message": "Path not found.",
                    "details": str(target),
                },
            )
        try:
            if target.is_file():
                _reveal_in_windows_explorer(target)
            else:
                os.startfile(str(target))  # type: ignore[attr-defined]
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "error_code": "OPEN_FOLDER_ERROR",
                    "message": "Could not open folder with the system shell.",
                    "details": str(exc),
                },
            ) from exc
        return {"status": "ok", "path": str(target)}

    @router.post("/projects", response_model=ProjectResponse)
    def create_project(payload: ProjectCreateRequest) -> ProjectResponse:
        try:
            project = ctx.repository.create_project(
                source_path=payload.source_path,
                device_mode=payload.device_mode,
                language_hint=payload.language_hint,
            )
            return _project_to_response(project)
        except DiaricatError as exc:
            _raise_http(exc)

    @router.get("/projects/{project_id}", response_model=ProjectResponse)
    def get_project(project_id: str) -> ProjectResponse:
        try:
            project = ctx.repository.get_project(project_id)
            return _project_to_response(project)
        except DiaricatError as exc:
            _raise_http(exc, status_code=404)

    @router.get("/projects/{project_id}/transcript", response_model=TranscriptDocument)
    def get_transcript(project_id: str) -> TranscriptDocument:
        try:
            return ctx.repository.get_transcript(project_id)
        except DiaricatError as exc:
            _raise_http(exc, status_code=404)

    @router.get("/projects/{project_id}/summary", response_model=SummaryDocument)
    def get_summary(project_id: str) -> SummaryDocument:
        try:
            summary = ctx.repository.get_summary(project_id)
            if summary is None:
                raise DiaricatError(
                    code=ErrorCode.NOT_FOUND,
                    message="Summary is not available for this project.",
                )
            return summary
        except DiaricatError as exc:
            _raise_http(exc, status_code=404)

    @router.post("/projects/{project_id}/run", response_model=JobStatusResponse)
    def run_pipeline(project_id: str, payload: RunPipelineRequest) -> JobStatusResponse:
        try:
            ctx.repository.get_project(project_id)
            job_id_holder: list[str] = []

            def pipeline_task(progress):
                return ctx.orchestrator.run_pipeline(
                    project_id,
                    run_correction=payload.run_correction,
                    run_summary=payload.run_summary,
                    progress=progress,
                    is_cancelled=lambda: bool(job_id_holder) and ctx.jobs.is_cancelled(job_id_holder[0]),
                )

            job = ctx.jobs.submit(
                project_id=project_id,
                kind="pipeline",
                task=pipeline_task,
            )
            job_id_holder.append(job.job_id)
            _api_log.info(
                "Pipeline job submitted.",
                extra={
                    "ctx_project_id": project_id,
                    "ctx_job_id": job.job_id,
                    "ctx_run_correction": payload.run_correction,
                    "ctx_run_summary": payload.run_summary,
                },
            )
            return _job_to_response(job)
        except DiaricatError as exc:
            _raise_http(exc)

    @router.post("/projects/{project_id}/correct", response_model=JobStatusResponse)
    def correct_project(project_id: str) -> JobStatusResponse:
        try:
            ctx.repository.get_project(project_id)
            job = ctx.jobs.submit(
                project_id=project_id,
                kind="correct",
                task=lambda progress: _correct_task(ctx, project_id, progress),
            )
            return _job_to_response(job)
        except DiaricatError as exc:
            _raise_http(exc)

    @router.post("/projects/{project_id}/summarize", response_model=JobStatusResponse)
    def summarize_project(project_id: str) -> JobStatusResponse:
        try:
            ctx.repository.get_project(project_id)
            job = ctx.jobs.submit(
                project_id=project_id,
                kind="summarize",
                task=lambda progress: _summary_task(ctx, project_id, progress),
            )
            return _job_to_response(job)
        except DiaricatError as exc:
            _raise_http(exc)

    @router.post("/projects/{project_id}/speakers/rename", response_model=dict[str, Any])
    def rename_speakers(project_id: str, payload: RenameSpeakersRequest) -> dict[str, Any]:
        try:
            transcript = ctx.orchestrator.rename_speakers(project_id, payload.mapping)
            return {
                "project_id": project_id,
                "updated_segments": len(transcript.segments),
                "mapping": payload.mapping,
            }
        except DiaricatError as exc:
            _raise_http(exc)

    @router.post("/projects/{project_id}/export", response_model=dict[str, Any])
    def export_project(project_id: str, payload: ExportRequest) -> dict[str, Any]:
        try:
            formats = payload.formats or [
                ExportFormat.JSON,
                ExportFormat.MD,
                ExportFormat.TXT,
                ExportFormat.PDF,
                ExportFormat.DOCX,
            ]
            artifacts = ctx.orchestrator.export_project(
                project_id=project_id,
                formats=formats,
                include_timestamps=payload.include_timestamps,
            )
            return {"project_id": project_id, "artifacts": artifacts}
        except DiaricatError as exc:
            _raise_http(exc)

    @router.get("/settings", response_model=AppSettingsResponse)
    def get_settings() -> AppSettingsResponse:
        return _settings_to_response(ctx)

    @router.patch("/settings", response_model=AppSettingsResponse)
    def update_settings(payload: AppSettingsUpdateRequest) -> AppSettingsResponse:
        s = ctx.settings.services
        if payload.whisper_model is not None:
            s.whisper_model = payload.whisper_model
        if payload.whisper_compute_type is not None:
            s.whisper_compute_type = payload.whisper_compute_type
        if payload.hf_token is not None:
            s.hf_token = payload.hf_token
        if payload.llama_model_path is not None:
            s.llama_model_path = Path(payload.llama_model_path)
        if payload.llama_n_ctx is not None:
            s.llama_n_ctx = payload.llama_n_ctx
        if payload.llama_n_threads is not None:
            s.llama_n_threads = payload.llama_n_threads
        if payload.whisper_chunk_seconds is not None:
            s.whisper_chunk_seconds = payload.whisper_chunk_seconds
        if payload.whisper_beam_size is not None:
            s.whisper_beam_size = payload.whisper_beam_size
        if payload.whisper_cpu_threads is not None:
            s.whisper_cpu_threads = payload.whisper_cpu_threads
        if payload.summary_chunk_chars is not None:
            s.summary_chunk_chars = payload.summary_chunk_chars
        if payload.diarization_profile is not None:
            s.diarization_profile = payload.diarization_profile
        if payload.workspace_dir is not None:
            ctx.settings.app.workspace_dir = Path(payload.workspace_dir)
        if payload.fullscreen_on_maximize is not None:
            ctx.settings.app.fullscreen_on_maximize = payload.fullscreen_on_maximize
        save_settings(ctx.settings)
        _api_log.info(
            "Settings updated.",
            extra={
                "ctx_whisper_model": s.whisper_model,
                "ctx_whisper_compute_type": s.whisper_compute_type,
                "ctx_whisper_chunk_seconds": s.whisper_chunk_seconds,
                "ctx_whisper_beam_size": s.whisper_beam_size,
                "ctx_whisper_cpu_threads": s.whisper_cpu_threads,
                "ctx_summary_chunk_chars": s.summary_chunk_chars,
                "ctx_diarization_profile": s.diarization_profile,
            },
        )
        return _settings_to_response(ctx)

    @router.get("/jobs/{job_id}", response_model=JobStatusResponse)
    def get_job(job_id: str) -> JobStatusResponse:
        try:
            return _job_to_response(ctx.jobs.get(job_id))
        except DiaricatError as exc:
            _raise_http(exc, status_code=404)

    @router.post("/jobs/{job_id}/cancel", response_model=JobStatusResponse)
    def cancel_job(job_id: str) -> JobStatusResponse:
        try:
            return _job_to_response(ctx.jobs.cancel(job_id))
        except DiaricatError as exc:
            _raise_http(exc, status_code=404)

    @router.get("/projects/{project_id}/artifacts", response_model=dict[str, Any])
    def list_artifacts(project_id: str) -> dict[str, Any]:
        try:
            project = ctx.repository.get_project(project_id)
            return {
                "project_id": project_id,
                "pipeline_state": project.pipeline_state,
                "artifacts": ctx.repository.list_artifacts(project_id),
            }
        except DiaricatError as exc:
            _raise_http(exc, status_code=404)

    app.include_router(router)

    frontend_dist = _resolve_frontend_dist()
    if frontend_dist is not None:
        # Mount UI after API routes so /v1/* always resolves to backend handlers first.
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


def _correct_task(ctx: AppContext, project_id: str, progress) -> dict[str, str]:
    progress("correction", 10)
    ctx.orchestrator.correct_project(project_id)
    progress("correction", 100)
    return {"project_id": project_id, "state": "CORRECTED"}


def _summary_task(ctx: AppContext, project_id: str, progress) -> dict[str, str]:
    progress("summary", 10)
    ctx.orchestrator.summarize_project(project_id)
    progress("summary", 100)
    return {"project_id": project_id, "state": "SUMMARIZED"}


def run_api_server(host: str | None = None, port: int | None = None) -> None:
    context = get_context()
    app = create_app(context)
    uvicorn.run(
        app,
        host=host or context.settings.app.host,
        port=port or context.settings.app.port,
        log_config=None,
        access_log=False,
    )
