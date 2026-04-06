"""Unified entrypoint for CLI, API and packaged desktop mode."""

from __future__ import annotations

import logging
import os
import platform
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


def _ensure_runtime_cwd() -> None:
    # In packaged mode, resources are resolved relative to the executable folder.
    if getattr(sys, "frozen", False):
        os.chdir(Path(sys.executable).resolve().parent)


def _early_logging() -> None:
    """Minimal console logging before full log system is ready."""
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="[%(levelname)s] %(name)s: %(message)s",
        )


def _startup_trace_enabled() -> bool:
    value = os.environ.get("DIARICAT_STARTUP_TRACE", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _startup_trace_path() -> Path:
    raw = os.environ.get("DIARICAT_STARTUP_TRACE_PATH", "").strip()
    if raw:
        return Path(raw)
    return Path.cwd() / "startup-trace.log"


def _startup_trace(message: str) -> None:
    if not _startup_trace_enabled():
        return
    try:
        trace_path = _startup_trace_path()
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat()
        line = f"{timestamp} pid={os.getpid()} {message}\n"
        with trace_path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        # Tracing must never block startup.
        return


def run() -> None:
    _ensure_runtime_cwd()
    _startup_trace(f"cwd={Path.cwd()} argv={sys.argv!r}")
    _early_logging()

    log = logging.getLogger("diaricat.main")
    log.info(
        "Diaricat starting — python=%s os=%s %s frozen=%s",
        platform.python_version(),
        platform.system(),
        platform.release(),
        getattr(sys, "frozen", False),
    )
    _startup_trace("early_logging_ready")

    try:
        # Packaged app default: double-click opens desktop mode.
        if len(sys.argv) == 1:
            _startup_trace("entrypoint=desktop_default")
            run_desktop()
            return

        if len(sys.argv) > 1 and sys.argv[1] == "api":
            host = None
            port = None
            args = sys.argv[2:]
            for i, token in enumerate(args):
                if token == "--host" and i + 1 < len(args):
                    host = args[i + 1]
                if token == "--port" and i + 1 < len(args):
                    try:
                        port = int(args[i + 1])
                    except ValueError:
                        log.error("Invalid port value: %s", args[i + 1])
                        _startup_trace(f"invalid_port_value={args[i + 1]!r}")
                        sys.exit(1)
            _startup_trace(f"entrypoint=api host={host!r} port={port!r}")
            run_api_server(host=host, port=port)
            return

        if len(sys.argv) > 1 and sys.argv[1] == "desktop":
            _startup_trace("entrypoint=desktop_explicit")
            run_desktop()
            return

        _startup_trace("entrypoint=cli")
        from diaricat.cli.app import app as cli_app
        cli_app()
    except Exception as exc:
        _startup_trace(f"fatal_exception={exc.__class__.__name__}: {exc}")
        _startup_trace(traceback.format_exc().strip())
        raise


def run_desktop() -> None:
    _startup_trace("run_desktop_import")
    from diaricat.desktop import run_desktop_app
    _startup_trace("run_desktop_start")
    run_desktop_app()


def run_api() -> None:
    _startup_trace("run_api_import")
    from diaricat.api.app import run_api_server
    _startup_trace("run_api_start")
    run_api_server()


def run_api_server(host=None, port=None):
    _startup_trace("run_api_server_import")
    from diaricat.api.app import run_api_server as _run
    _startup_trace(f"run_api_server_start host={host!r} port={port!r}")
    _run(host=host, port=port)


if __name__ == "__main__":
    run()
