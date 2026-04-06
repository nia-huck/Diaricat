"""Error catalog and domain exceptions."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    FFMPEG_ERROR = "FFMPEG_ERROR"
    ASR_ERROR = "ASR_ERROR"
    DIARIZATION_ERROR = "DIARIZATION_ERROR"
    POSTPROCESS_ERROR = "POSTPROCESS_ERROR"
    EXPORT_ERROR = "EXPORT_ERROR"
    PIPELINE_ERROR = "PIPELINE_ERROR"
    NOT_FOUND = "NOT_FOUND"
    GPU_UNAVAILABLE = "GPU_UNAVAILABLE"


class DiaricatError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: str | None = None,
        failure_component: str | None = None,
        error_hint: str | None = None,
        attempt: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.failure_component = failure_component
        self.error_hint = error_hint
        self.attempt = attempt

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "error_code": str(self.code),
            "message": self.message,
            "details": self.details,
            "failure_component": self.failure_component,
            "error_hint": self.error_hint,
            "attempt": self.attempt,
        }
