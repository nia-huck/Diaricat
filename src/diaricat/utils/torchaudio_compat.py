"""Compatibility helpers for torchaudio API changes."""

from __future__ import annotations


def ensure_speechbrain_torchaudio_compat() -> None:
    """
    Provide backward-compatible torchaudio symbols expected by SpeechBrain.

    torchaudio >= 2.10 removed the global backend API (`list_audio_backends`,
    `set_audio_backend`, `get_audio_backend`). SpeechBrain still references
    these symbols during import. This shim restores no-op equivalents so local
    diarization can initialize without patching third-party code.
    """
    try:
        import torchaudio  # type: ignore
    except Exception:
        return

    if not hasattr(torchaudio, "list_audio_backends"):
        setattr(torchaudio, "list_audio_backends", lambda: ["dispatcher"])

    if not hasattr(torchaudio, "set_audio_backend"):
        setattr(torchaudio, "set_audio_backend", lambda _backend=None: None)

    if not hasattr(torchaudio, "get_audio_backend"):
        setattr(torchaudio, "get_audio_backend", lambda: None)

