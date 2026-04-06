from __future__ import annotations

import math
import struct
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from diaricat.errors import DiaricatError, ErrorCode
from diaricat.models.domain import DeviceMode
from diaricat.services.diarization_service import PyannoteDiarizationService


def _create_wav(path: Path, seconds: float = 1.0, sample_rate: int = 16000) -> None:
    total = int(sample_rate * seconds)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for i in range(total):
            value = int(12000 * math.sin(2 * math.pi * 220 * (i / sample_rate)))
            wav.writeframesraw(struct.pack("<h", value))


def test_local_backend_error_falls_back_to_single_speaker(tmp_path: Path, temp_settings, monkeypatch) -> None:
    audio = tmp_path / "sample.wav"
    _create_wav(audio, seconds=1.5)
    service = PyannoteDiarizationService(temp_settings)

    def _raise_load_error(_: Path) -> tuple[object, int]:
        raise DiaricatError(ErrorCode.DIARIZATION_ERROR, "backend unavailable")

    monkeypatch.setattr(service, "_load_audio", _raise_load_error)

    turns = service.diarize(audio, DeviceMode.CPU)

    assert len(turns) == 1
    assert turns[0].speaker_id == "SPEAKER_00"
    assert turns[0].start == 0.0
    assert turns[0].end > 1.0


def test_unknown_profile_uses_balanced(tmp_path: Path, temp_settings) -> None:
    temp_settings.services.diarization_profile = "unknown"
    service = PyannoteDiarizationService(temp_settings)
    profile = service._get_profile()
    assert profile.window_s == 1.5
    assert profile.hop_s == 0.75


def test_local_diarization_detects_multiple_speakers_on_distinct_sections(
    tmp_path: Path, temp_settings
) -> None:
    temp_settings.services.diarization_profile = "quality"
    sample_rate = 16000
    total_seconds = 4.0
    total = int(sample_rate * total_seconds)

    samples = []
    for i in range(total):
        t = i / sample_rate
        if t < 2.0:
            freq = 180.0
        else:
            freq = 420.0
        value = int(11000 * math.sin(2 * math.pi * freq * t))
        samples.append(struct.pack("<h", value))

    audio = tmp_path / "two_speakers.wav"
    with wave.open(str(audio), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"".join(samples))

    service = PyannoteDiarizationService(temp_settings)
    turns = service.diarize(audio, DeviceMode.CPU)
    speakers = {turn.speaker_id for turn in turns}

    assert len(speakers) >= 2


def test_clustering_merges_tiny_outlier_cluster(temp_settings) -> None:
    temp_settings.services.diarization_profile = "quality"
    service = PyannoteDiarizationService(temp_settings)
    profile = service._get_profile()

    rng = np.random.default_rng(42)
    cluster_a = rng.normal(loc=-1.0, scale=0.15, size=(60, 8)).astype(np.float32)
    cluster_b = rng.normal(loc=1.0, scale=0.15, size=(80, 8)).astype(np.float32)
    outlier = np.array([[12.0] * 8], dtype=np.float32)
    features = np.vstack([cluster_a, cluster_b, outlier]).astype(np.float32)

    labels = service._cluster_features(features, profile)
    unique, counts = np.unique(labels, return_counts=True)

    assert unique.size >= 2
    assert int(np.min(counts)) >= 10


def test_embedder_uses_copy_local_strategy(temp_settings, monkeypatch) -> None:
    called: dict[str, object] = {}

    class FakeEncoderClassifier:
        @classmethod
        def from_hparams(cls, **kwargs):  # noqa: ANN206
            called.update(kwargs)
            return object()

    fake_local_strategy = SimpleNamespace(COPY="copy")
    monkeypatch.setattr(
        "diaricat.services.diarization_service.ensure_speechbrain_runtime_compat",
        lambda: None,
    )
    monkeypatch.setitem(
        sys.modules,
        "speechbrain.inference.speaker",
        SimpleNamespace(EncoderClassifier=FakeEncoderClassifier),
    )
    monkeypatch.setitem(
        sys.modules,
        "speechbrain.utils.fetching",
        SimpleNamespace(LocalStrategy=fake_local_strategy),
    )

    service = PyannoteDiarizationService(temp_settings)
    embedder = service._get_embedder()

    assert embedder is not None
    assert called.get("local_strategy") == "copy"


def test_embedder_cache_is_device_aware(temp_settings, monkeypatch) -> None:
    seen_devices: list[str] = []

    class FakeEncoderClassifier:
        @classmethod
        def from_hparams(cls, **kwargs):  # noqa: ANN206
            run_opts = kwargs.get("run_opts", {})
            seen_devices.append(str(run_opts.get("device", "cpu")))
            return object()

    fake_local_strategy = SimpleNamespace(COPY="copy")
    monkeypatch.setattr(
        "diaricat.services.diarization_service.ensure_speechbrain_runtime_compat",
        lambda: None,
    )
    monkeypatch.setitem(
        sys.modules,
        "speechbrain.inference.speaker",
        SimpleNamespace(EncoderClassifier=FakeEncoderClassifier),
    )
    monkeypatch.setitem(
        sys.modules,
        "speechbrain.utils.fetching",
        SimpleNamespace(LocalStrategy=fake_local_strategy),
    )

    service = PyannoteDiarizationService(temp_settings)
    embedder_cpu = service._get_embedder(device="cpu")
    embedder_cuda = service._get_embedder(device="cuda")
    embedder_cpu_again = service._get_embedder(device="cpu")

    assert embedder_cpu is not None
    assert embedder_cuda is not None
    assert embedder_cpu_again is embedder_cpu
    assert seen_devices.count("cpu") == 1
    assert seen_devices.count("cuda") == 1


def test_silhouette_sampling_limits_rows(temp_settings) -> None:
    service = PyannoteDiarizationService(temp_settings)
    n = 800
    labels = np.array([i % 3 for i in range(n)], dtype=np.int32)
    # Symmetric distance matrix with zero diagonal.
    rng = np.random.default_rng(7)
    values = rng.uniform(0.0, 1.0, size=(n, n)).astype(np.float32)
    dist = (values + values.T) / 2.0
    np.fill_diagonal(dist, 0.0)

    score = service._silhouette_score_cosine(dist, labels, max_samples=64)

    assert isinstance(score, float)
    assert np.isfinite(score)
