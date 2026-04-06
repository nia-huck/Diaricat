"""Path and file IO helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from diaricat.settings import Settings


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_runtime_dirs(settings: Settings) -> None:
    ensure_dir(settings.app.workspace_dir)
    ensure_dir(settings.app.workspace_dir / "projects")
    ensure_dir(settings.app.workspace_dir / "jobs")
    ensure_dir(settings.app.temp_dir)
    ensure_dir(settings.app.log_dir)


def project_dir(settings: Settings, project_id: str) -> Path:
    return ensure_dir(settings.app.workspace_dir / "projects" / project_id)


def project_exports_dir(settings: Settings, project_id: str) -> Path:
    return ensure_dir(project_dir(settings, project_id) / "exports")


def project_temp_dir(settings: Settings, project_id: str) -> Path:
    return ensure_dir(settings.app.temp_dir / project_id)


def jobs_dir(settings: Settings) -> Path:
    return ensure_dir(settings.app.workspace_dir / "jobs")


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding=encoding)
    os.replace(tmp, path)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
