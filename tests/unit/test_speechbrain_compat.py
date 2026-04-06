from __future__ import annotations

import sys
from types import SimpleNamespace

from diaricat.utils.speechbrain_compat import ensure_speechbrain_runtime_compat


def test_runtime_compat_maps_use_auth_token_to_token(monkeypatch):
    captured: dict[str, object] = {}

    def _hf_hub_download(*args, token=None, **kwargs):  # noqa: ANN001
        captured["args"] = args
        captured["token"] = token
        captured["kwargs"] = kwargs
        return "ok"

    monkeypatch.setitem(sys.modules, "torchaudio", SimpleNamespace(__version__="2.10.0"))
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(hf_hub_download=_hf_hub_download))

    ensure_speechbrain_runtime_compat()

    import huggingface_hub  # type: ignore

    result = huggingface_hub.hf_hub_download("repo", "file", use_auth_token="secret-token")
    assert result == "ok"
    assert captured["token"] == "secret-token"
