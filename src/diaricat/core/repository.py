"""Project persistence on local filesystem."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from diaricat.errors import DiaricatError, ErrorCode
from diaricat.models.domain import (
    DeviceMode,
    PipelineState,
    Project,
    SummaryDocument,
    TranscriptDocument,
)
from diaricat.settings import Settings
from diaricat.utils.paths import atomic_write_json, project_dir, read_json


class ProjectRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _project_lock(self, project_id: str) -> threading.Lock:
        with self._locks_guard:
            if project_id not in self._locks:
                self._locks[project_id] = threading.Lock()
            return self._locks[project_id]

    def _project_file(self, project_id: str) -> Path:
        return project_dir(self.settings, project_id) / "project.json"

    def _transcript_file(self, project_id: str) -> Path:
        return project_dir(self.settings, project_id) / "transcript.json"

    def _summary_file(self, project_id: str) -> Path:
        return project_dir(self.settings, project_id) / "summary.json"

    def _speaker_map_file(self, project_id: str) -> Path:
        return project_dir(self.settings, project_id) / "speaker_map.json"

    def create_project(self, source_path: str, device_mode: DeviceMode, language_hint: str = "auto") -> Project:
        project = Project(
            id=uuid.uuid4().hex,
            source_path=source_path,
            device_mode=device_mode,
            language_hint=language_hint,
        )
        self.save_project(project)
        return project

    def get_project(self, project_id: str) -> Project:
        path = self._project_file(project_id)
        if not path.exists():
            raise DiaricatError(ErrorCode.NOT_FOUND, f"Project '{project_id}' not found.")
        return Project.model_validate(read_json(path))

    def save_project(self, project: Project) -> Project:
        with self._project_lock(project.id):
            project.updated_at = datetime.now(tz=timezone.utc)
            atomic_write_json(self._project_file(project.id), project.model_dump(mode="json"))
            return project

    def set_state(
        self,
        project_id: str,
        state: PipelineState,
        error_code: str | None = None,
        error_detail: str | None = None,
        failure_component: str | None = None,
        error_hint: str | None = None,
        attempt: int | None = None,
    ) -> Project:
        with self._project_lock(project_id):
            project = self.get_project(project_id)
            project.pipeline_state = state
            project.error_code = error_code
            project.error_detail = error_detail
            project.failure_component = failure_component
            project.error_hint = error_hint
            project.attempt = attempt
            project.updated_at = datetime.now(tz=timezone.utc)
            atomic_write_json(self._project_file(project_id), project.model_dump(mode="json"))
            return project

    def save_transcript(self, project_id: str, transcript: TranscriptDocument) -> None:
        with self._project_lock(project_id):
            atomic_write_json(self._transcript_file(project_id), transcript.model_dump(mode="json"))

    def get_transcript(self, project_id: str) -> TranscriptDocument:
        path = self._transcript_file(project_id)
        if not path.exists():
            raise DiaricatError(
                ErrorCode.NOT_FOUND,
                f"Transcript for project '{project_id}' was not found.",
            )
        return TranscriptDocument.model_validate(read_json(path))

    def save_summary(self, project_id: str, summary: SummaryDocument) -> None:
        with self._project_lock(project_id):
            atomic_write_json(self._summary_file(project_id), summary.model_dump(mode="json"))

    def get_summary(self, project_id: str) -> SummaryDocument | None:
        path = self._summary_file(project_id)
        if not path.exists():
            return None
        return SummaryDocument.model_validate(read_json(path))

    def save_speaker_map(self, project_id: str, mapping: dict[str, str]) -> None:
        with self._project_lock(project_id):
            atomic_write_json(self._speaker_map_file(project_id), {"mapping": mapping})

    def add_artifacts(self, project_id: str, artifacts: dict[str, str]) -> Project:
        with self._project_lock(project_id):
            project = self.get_project(project_id)
            project.artifacts.update(artifacts)
            project.updated_at = datetime.now(tz=timezone.utc)
            atomic_write_json(self._project_file(project_id), project.model_dump(mode="json"))
            return project

    def list_artifacts(self, project_id: str) -> dict[str, str]:
        project = self.get_project(project_id)
        return dict(project.artifacts)
