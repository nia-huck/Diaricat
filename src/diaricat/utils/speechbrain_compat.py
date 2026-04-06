"""Runtime compatibility shims for SpeechBrain dependencies."""

from __future__ import annotations

import inspect
from typing import Any

from diaricat.utils.torchaudio_compat import ensure_speechbrain_torchaudio_compat


def _patch_hf_hub_download_for_use_auth_token() -> None:
    try:
        import huggingface_hub  # type: ignore
    except Exception:
        return

    hf_hub_download = getattr(huggingface_hub, "hf_hub_download", None)
    if not callable(hf_hub_download):
        return

    if getattr(hf_hub_download, "__diaricat_compat__", False):
        return

    try:
        parameters = inspect.signature(hf_hub_download).parameters
    except Exception:
        parameters = {}

    if "use_auth_token" in parameters:
        return

    original = hf_hub_download

    def _wrapped_hf_hub_download(*args: Any, **kwargs: Any) -> Any:
        use_auth_token = kwargs.pop("use_auth_token", None)
        if use_auth_token is not None and "token" not in kwargs:
            kwargs["token"] = use_auth_token
        try:
            return original(*args, **kwargs)
        except Exception as exc:
            # SpeechBrain treats missing optional custom.py as ValueError.
            # Newer huggingface_hub raises RemoteEntryNotFoundError instead.
            filename = str(kwargs.get("filename") or "")
            if filename == "custom.py" and exc.__class__.__name__ in {
                "RemoteEntryNotFoundError",
                "EntryNotFoundError",
            }:
                raise ValueError("Optional speechbrain custom.py not found.") from exc
            raise

    setattr(_wrapped_hf_hub_download, "__diaricat_compat__", True)
    huggingface_hub.hf_hub_download = _wrapped_hf_hub_download


def ensure_speechbrain_runtime_compat() -> None:
    """Apply compatibility shims required for current SpeechBrain stack."""
    ensure_speechbrain_torchaudio_compat()
    _patch_hf_hub_download_for_use_auth_token()
