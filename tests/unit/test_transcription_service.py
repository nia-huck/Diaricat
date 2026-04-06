from __future__ import annotations

from pathlib import Path

import pytest

from diaricat.errors import DiaricatError, ErrorCode
from diaricat.models.domain import DeviceMode
from diaricat.services.transcription_service import WhisperTranscriptionService


class _FakeSegment:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


class _FakeInfo:
    language = "es"


class _FakeModel:
    @staticmethod
    def transcribe(*_args, **_kwargs):
        return [
            _FakeSegment(0.0, 1.0, "hola"),
            _FakeSegment(1.0, 2.0, "mundo"),
        ], _FakeInfo()


def test_transcribe_returns_segments_and_metadata(temp_settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service = WhisperTranscriptionService(temp_settings)

    monkeypatch.setattr("diaricat.services.transcription_service.select_asr_runtime_device", lambda *_: "cpu")
    monkeypatch.setattr(service, "_load_model", lambda model_name, runtime_device: (_FakeModel(), "int8"))
    monkeypatch.setattr(service, "_model_candidates", lambda: ["small"])
    monkeypatch.setattr(service, "_wav_duration", lambda _: 2.0)
    monkeypatch.setattr(
        service,
        "_split_wav_into_chunks",
        lambda audio_path, chunk_seconds: [(audio_path, 0.0, 2.0)],
    )

    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"dummy")

    segments, metadata = service.transcribe(audio_path, "auto", DeviceMode.AUTO)

    assert len(segments) == 2
    assert metadata["segment_count"] == 2
    assert metadata["duration_s"] == 2.0
    assert metadata["language_detected"] == "es"
    assert metadata["fallbacks_applied"] == []


def test_transcribe_honors_cancellation(temp_settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service = WhisperTranscriptionService(temp_settings)
    monkeypatch.setattr("diaricat.services.transcription_service.select_asr_runtime_device", lambda *_: "cpu")
    monkeypatch.setattr(service, "_load_model", lambda model_name, runtime_device: (_FakeModel(), "int8"))
    monkeypatch.setattr(service, "_model_candidates", lambda: ["small"])
    monkeypatch.setattr(service, "_wav_duration", lambda _: 10.0)
    monkeypatch.setattr(
        service,
        "_split_wav_into_chunks",
        lambda audio_path, chunk_seconds: [(audio_path, 0.0, 10.0)],
    )

    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"dummy")

    with pytest.raises(DiaricatError) as exc_info:
        service.transcribe(
            audio_path,
            "auto",
            DeviceMode.AUTO,
            is_cancelled=lambda: True,
        )

    assert exc_info.value.code == ErrorCode.PIPELINE_ERROR
