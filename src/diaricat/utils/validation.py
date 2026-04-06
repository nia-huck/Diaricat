"""Validation helpers."""

from __future__ import annotations

from pathlib import Path

from diaricat.errors import DiaricatError, ErrorCode

ALLOWED_EXTENSIONS = {".mp4", ".mp3", ".wav", ".mkv"}


def validate_source_path(source_path: str) -> Path:
    path = Path(source_path)
    if not path.exists() or not path.is_file():
        raise DiaricatError(ErrorCode.VALIDATION_ERROR, "Input file not found", details=source_path)
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise DiaricatError(
            ErrorCode.VALIDATION_ERROR,
            f"Unsupported extension: {path.suffix}",
            details=f"Allowed: {allowed}",
        )
    return path


def sec_to_timestamp(value: float) -> str:
    total_ms = int(max(value, 0) * 1000)
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
