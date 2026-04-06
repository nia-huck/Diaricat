"""Pydantic models for runtime settings."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from diaricat.models.domain import DeviceMode


class AppConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765
    workspace_dir: Path = Path("workspace")
    temp_dir: Path = Path("temp")
    log_dir: Path = Path("logs")
    setup_done: bool = False
    fullscreen_on_maximize: bool = False

    def model_post_init(self, __context: object) -> None:
        # Enforce localhost-only binding — Diaricat is a local private app.
        _allowed_hosts = {"127.0.0.1", "localhost", "::1"}
        if self.host not in _allowed_hosts:
            import warnings
            warnings.warn(
                f"Non-local host '{self.host}' in config reset to 127.0.0.1. "
                "Diaricat only binds to localhost.",
                stacklevel=2,
            )
            self.host = "127.0.0.1"


class DeviceConfig(BaseModel):
    default_mode: DeviceMode = DeviceMode.AUTO


class ServicesConfig(BaseModel):
    ffmpeg_bin_dir: str | None = None
    whisper_model: str = "small"
    whisper_compute_type: str = "int8"
    pyannote_model: str = "pyannote/speaker-diarization-3.1"
    hf_token: str = ""
    hf_token_env: str = "HUGGINGFACE_TOKEN"
    llama_model_path: Path = Path("models/postprocess.gguf")
    llama_n_ctx: int = 4096
    llama_n_threads: int = 4
    whisper_chunk_seconds: int = Field(default=120, ge=30, le=900)
    whisper_beam_size: int = Field(default=5, ge=1, le=10)
    whisper_cpu_threads: int = Field(default=4, ge=1, le=32)
    summary_chunk_chars: int = Field(default=6000, ge=1200, le=20000)
    diarization_profile: str = "balanced"
    correction_ratio_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    correction_max_length_delta: float = Field(default=0.35, ge=0.0, le=1.0)


class Settings(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    device: DeviceConfig = Field(default_factory=DeviceConfig)
    services: ServicesConfig = Field(default_factory=ServicesConfig)


def _default_config_candidates() -> list[Path]:
    candidates: list[Path] = [Path("config/default.yaml")]
    if getattr(sys, "frozen", False):
        bundled_root = getattr(sys, "_MEIPASS", None)
        if bundled_root:
            candidates.append(Path(bundled_root) / "config" / "default.yaml")
    return candidates


def load_settings(config_path: Path | None = None) -> Settings:
    if config_path is not None:
        candidate_paths = [config_path]
    else:
        candidate_paths = _default_config_candidates()

    cfg_path = next((path for path in candidate_paths if path.exists()), None)
    if cfg_path is None:
        # Fresh install — show setup wizard on first launch.
        return Settings()
    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        import logging as _log
        _log.getLogger("diaricat.settings").warning(
            "Failed to parse config %s: %s — using defaults", cfg_path, exc
        )
        return Settings()
    # Upgrade paths: backfill keys added after initial release
    if "app" not in data or "setup_done" not in (data.get("app") or {}):
        data.setdefault("app", {})["setup_done"] = True
    if "app" not in data or "fullscreen_on_maximize" not in (data.get("app") or {}):
        data.setdefault("app", {})["fullscreen_on_maximize"] = False
    try:
        return Settings.model_validate(data)
    except Exception as exc:
        import logging as _log
        _log.getLogger("diaricat.settings").warning(
            "Settings validation error: %s — using defaults", exc
        )
        return Settings()


def save_settings(settings: Settings, config_path: Path | None = None) -> None:
    cfg_path = config_path or Path("config/default.yaml")
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "app": {
            "host": settings.app.host,
            "port": settings.app.port,
            "workspace_dir": str(settings.app.workspace_dir),
            "temp_dir": str(settings.app.temp_dir),
            "log_dir": str(settings.app.log_dir),
            "setup_done": settings.app.setup_done,
            "fullscreen_on_maximize": settings.app.fullscreen_on_maximize,
        },
        "device": {
            "default_mode": settings.device.default_mode.value,
        },
        "services": {
            "ffmpeg_bin_dir": settings.services.ffmpeg_bin_dir or "",
            "whisper_model": settings.services.whisper_model,
            "whisper_compute_type": settings.services.whisper_compute_type,
            "pyannote_model": settings.services.pyannote_model,
            "hf_token": settings.services.hf_token,
            "hf_token_env": settings.services.hf_token_env,
            "llama_model_path": str(settings.services.llama_model_path),
            "llama_n_ctx": settings.services.llama_n_ctx,
            "llama_n_threads": settings.services.llama_n_threads,
            "whisper_chunk_seconds": settings.services.whisper_chunk_seconds,
            "whisper_beam_size": settings.services.whisper_beam_size,
            "whisper_cpu_threads": settings.services.whisper_cpu_threads,
            "summary_chunk_chars": settings.services.summary_chunk_chars,
            "diarization_profile": settings.services.diarization_profile,
            "correction_ratio_threshold": settings.services.correction_ratio_threshold,
            "correction_max_length_delta": settings.services.correction_max_length_delta,
        },
    }
    cfg_path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")
