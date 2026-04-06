from __future__ import annotations

from pathlib import Path

import pytest

from diaricat.errors import DiaricatError, ErrorCode
from diaricat.services.audio_service import AudioService


def test_validate_returns_actionable_error_if_ffprobe_missing(tmp_path: Path, temp_settings) -> None:
    source = tmp_path / "sample.wav"
    source.write_text("dummy", encoding="utf-8")
    service = AudioService(temp_settings)

    import diaricat.services.audio_service as audio_module

    def _raise_missing(*_args, **_kwargs):
        raise FileNotFoundError("ffprobe not found")

    original_run = audio_module.subprocess.run
    audio_module.subprocess.run = _raise_missing
    try:
        with pytest.raises(DiaricatError) as exc_info:
            service.validate(str(source))
    finally:
        audio_module.subprocess.run = original_run

    exc = exc_info.value
    assert exc.code == ErrorCode.FFMPEG_ERROR
    assert "ffprobe binary was not found" in exc.message
    assert exc.details is not None
    assert "Expected command:" in exc.details


def test_normalize_returns_actionable_error_if_ffmpeg_missing(tmp_path: Path, temp_settings) -> None:
    source = tmp_path / "sample.wav"
    source.write_text("dummy", encoding="utf-8")
    service = AudioService(temp_settings)

    import diaricat.services.audio_service as audio_module

    def _raise_missing(*_args, **_kwargs):
        raise FileNotFoundError("ffmpeg not found")

    original_run = audio_module.subprocess.run
    audio_module.subprocess.run = _raise_missing
    try:
        with pytest.raises(DiaricatError) as exc_info:
            service.normalize_to_wav("p-test", source)
    finally:
        audio_module.subprocess.run = original_run

    exc = exc_info.value
    assert exc.code == ErrorCode.FFMPEG_ERROR
    assert "ffmpeg binary was not found" in exc.message
    assert exc.details is not None
    assert "Expected command:" in exc.details
