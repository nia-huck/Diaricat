"""Domain types shared by API, CLI and orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class DeviceMode(StrEnum):
    AUTO = "auto"
    CPU = "cpu"
    GPU = "gpu"


class PipelineState(StrEnum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    AUDIO_READY = "AUDIO_READY"
    TRANSCRIBED = "TRANSCRIBED"
    DIARIZED = "DIARIZED"
    MERGED = "MERGED"
    CORRECTED = "CORRECTED"
    SUMMARIZED = "SUMMARIZED"
    EXPORTED = "EXPORTED"
    FAILED = "FAILED"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ExportFormat(StrEnum):
    JSON = "json"
    MD = "md"
    TXT = "txt"
    PDF = "pdf"
    DOCX = "docx"


class Project(BaseModel):
    id: str
    source_path: str
    device_mode: DeviceMode
    language_hint: str = "auto"
    pipeline_state: PipelineState = PipelineState.CREATED
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    error_code: str | None = None
    error_detail: str | None = None
    failure_component: str | None = None
    error_hint: str | None = None
    attempt: int | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)


class RawTranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


class SpeakerTurn(BaseModel):
    start: float
    end: float
    speaker_id: str


class SpeakerProfile(BaseModel):
    speaker_id: str
    custom_name: str | None = None
    color_ui: str = "#5B8FF9"


class TranscriptSegment(BaseModel):
    start: float
    end: float
    speaker_id: str
    speaker_name: str | None = None
    text_raw: str
    text_corrected: str | None = None


class TranscriptDocument(BaseModel):
    segments: list[TranscriptSegment] = Field(default_factory=list)
    full_text_raw: str = ""
    full_text_corrected: str | None = None
    quality_metadata: dict[str, Any] = Field(default_factory=dict)
    speaker_profiles: list[SpeakerProfile] = Field(default_factory=list)


class SummaryDocument(BaseModel):
    overview: str = ""
    key_points: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    citations: list[dict[str, Any]] | None = None


class JobRecord(BaseModel):
    job_id: str
    project_id: str
    kind: str
    stage: str = "queued"
    progress: int = 0
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    error_code: str | None = None
    error_detail: str | None = None
    failure_component: str | None = None
    error_hint: str | None = None
    attempt: int | None = None
    result: dict[str, Any] = Field(default_factory=dict)
