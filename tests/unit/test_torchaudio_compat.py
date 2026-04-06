from __future__ import annotations

import sys
from types import SimpleNamespace

from diaricat.utils.torchaudio_compat import ensure_speechbrain_torchaudio_compat


def test_compat_shim_adds_missing_torchaudio_backend_symbols(monkeypatch):
    fake_torchaudio = SimpleNamespace(__version__="2.10.0")
    monkeypatch.setitem(sys.modules, "torchaudio", fake_torchaudio)

    ensure_speechbrain_torchaudio_compat()

    assert hasattr(fake_torchaudio, "list_audio_backends")
    assert hasattr(fake_torchaudio, "set_audio_backend")
    assert hasattr(fake_torchaudio, "get_audio_backend")
    assert fake_torchaudio.list_audio_backends() == ["dispatcher"]


def test_compat_shim_keeps_existing_backend_symbols(monkeypatch):
    calls: list[str] = []

    def _list() -> list[str]:
        return ["ffmpeg"]

    def _set(name: str | None = None) -> None:
        calls.append(str(name))

    fake_torchaudio = SimpleNamespace(
        __version__="2.4.0",
        list_audio_backends=_list,
        set_audio_backend=_set,
        get_audio_backend=lambda: "ffmpeg",
    )
    monkeypatch.setitem(sys.modules, "torchaudio", fake_torchaudio)

    ensure_speechbrain_torchaudio_compat()

    assert fake_torchaudio.list_audio_backends() == ["ffmpeg"]
    fake_torchaudio.set_audio_backend("sox")
    assert calls == ["sox"]
