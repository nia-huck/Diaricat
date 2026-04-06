"""Structured logging setup — session-aware, rotation-enabled, security-separated."""

from __future__ import annotations

import json
import logging
import os
import platform
import threading
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

# ─── Session ID (one per process) ────────────────────────────────────────────
SESSION_ID: str = uuid.uuid4().hex[:12]

_lock = threading.Lock()
_configured = False


class JsonFormatter(logging.Formatter):
    """JSON line formatter with session and thread context."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record.levelname,
            "logger": record.name,
            "session": SESSION_ID,
            "thread": threading.current_thread().name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Attach any extra fields passed via `extra={...}`
        for key, value in record.__dict__.items():
            if key.startswith("ctx_") and key not in payload:
                payload[key[4:]] = value
        # Backward compatibility: some callers pass `extra={"extra": {...}}`.
        legacy_extra = getattr(record, "extra", None)
        if isinstance(legacy_extra, dict):
            for key, value in legacy_extra.items():
                if key not in payload:
                    payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


class ConsoleFmt(logging.Formatter):
    _COLORS = {
        "DEBUG":    "\033[36m",
        "INFO":     "\033[32m",
        "WARNING":  "\033[33m",
        "ERROR":    "\033[31m",
        "CRITICAL": "\033[35m",
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self._COLORS.get(record.levelname, "")
        reset = self._RESET if color else ""
        ts = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
        return f"{color}[{ts}] [{record.levelname:>8}] {record.name}: {record.getMessage()}{reset}"


def configure_logging(log_dir: Path, level: int = logging.INFO) -> None:
    global _configured

    with _lock:
        if _configured:
            return
        _configured = True

    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    env_level = os.environ.get("DIARICAT_LOG_LEVEL", "").strip().upper()
    if env_level:
        level = getattr(logging, env_level, level)
    root.setLevel(level)

    # Silence noisy third-party loggers
    for noisy in ("httpx", "httpcore", "urllib3", "filelock", "transformers", "torch"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    json_fmt = JsonFormatter()

    # ── Main rotating log ──────────────────────────────────────────────────
    main_handler = RotatingFileHandler(
        filename=log_dir / "diaricat.log",
        maxBytes=5_000_000,   # 5 MB
        backupCount=7,
        encoding="utf-8",
    )
    main_handler.setFormatter(json_fmt)
    main_handler.setLevel(logging.DEBUG)

    # ── Security log (WARNING+) ────────────────────────────────────────────
    sec_handler = RotatingFileHandler(
        filename=log_dir / "security.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    sec_handler.setFormatter(json_fmt)
    sec_handler.setLevel(logging.WARNING)

    # ── Console (INFO+, colored) ───────────────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(ConsoleFmt())
    console_handler.setLevel(logging.INFO)

    root.addHandler(main_handler)
    root.addHandler(sec_handler)
    root.addHandler(console_handler)

    # First log entry
    startup_logger = logging.getLogger("diaricat.startup")
    startup_logger.info(
        "Diaricat logging initialized",
        extra={
            "ctx_session": SESSION_ID,
            "ctx_log_dir": str(log_dir),
            "ctx_python": platform.python_version(),
            "ctx_os": f"{platform.system()} {platform.release()}",
            "ctx_pid": os.getpid(),
        },
    )


def get_security_logger() -> logging.Logger:
    """Return the dedicated security/audit logger."""
    return logging.getLogger("diaricat.security")


def log_pipeline_event(
    logger: logging.Logger,
    event: str,
    project_id: str,
    stage: str | None = None,
    elapsed_ms: int | None = None,
    **kw: Any,
) -> None:
    """Structured pipeline event helper."""
    extra: dict[str, Any] = {
        "ctx_event": event,
        "ctx_project": project_id,
    }
    if stage is not None:
        extra["ctx_stage"] = stage
    if elapsed_ms is not None:
        extra["ctx_elapsed_ms"] = elapsed_ms
    extra.update({f"ctx_{k}": v for k, v in kw.items()})
    logger.info("pipeline.%s project=%s", event, project_id, extra=extra)
