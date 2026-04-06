"""Application context wiring."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from diaricat.core.jobs import JobManager
from diaricat.core.orchestrator import PipelineOrchestrator
from diaricat.core.repository import ProjectRepository
from diaricat.services.alignment_service import AlignmentService
from diaricat.services.audio_service import AudioService
from diaricat.services.diarization_service import PyannoteDiarizationService
from diaricat.services.export_service import ExportService
from diaricat.services.postprocess_service import LocalPostprocessService
from diaricat.services.transcription_service import WhisperTranscriptionService
from diaricat.settings import Settings, load_settings
from diaricat.utils.logging import configure_logging
from diaricat.utils.paths import ensure_runtime_dirs


@dataclass
class AppContext:
    settings: Settings
    repository: ProjectRepository
    orchestrator: PipelineOrchestrator
    jobs: JobManager


_context_singleton: AppContext | None = None


def build_context(config_path: Path | None = None) -> AppContext:
    settings = load_settings(config_path)
    ensure_runtime_dirs(settings)
    configure_logging(settings.app.log_dir)
    startup_logger = logging.getLogger("diaricat.bootstrap")
    startup_logger.info(
        "Context initialized workspace=%s port=%s",
        settings.app.workspace_dir,
        settings.app.port,
    )

    repository = ProjectRepository(settings)

    orchestrator = PipelineOrchestrator(
        repository=repository,
        audio_service=AudioService(settings),
        transcription_service=WhisperTranscriptionService(settings),
        diarization_service=PyannoteDiarizationService(settings),
        alignment_service=AlignmentService(),
        postprocess_service=LocalPostprocessService(settings),
        export_service=ExportService(settings),
    )

    jobs = JobManager(settings)
    return AppContext(settings=settings, repository=repository, orchestrator=orchestrator, jobs=jobs)


def get_context(config_path: Path | None = None) -> AppContext:
    global _context_singleton
    if _context_singleton is None:
        _context_singleton = build_context(config_path)
    return _context_singleton


def reset_context() -> None:
    global _context_singleton
    if _context_singleton is not None:
        _context_singleton.jobs.stop()
    _context_singleton = None
