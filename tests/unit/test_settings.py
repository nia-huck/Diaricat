from __future__ import annotations

import sys
from pathlib import Path

from diaricat.settings import load_settings


def _write_yaml(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_load_settings_uses_local_config_by_default(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_yaml(
        tmp_path / "config" / "default.yaml",
        "app:\n"
        "  port: 9911\n"
        "services:\n"
        "  whisper_model: medium\n",
    )

    settings = load_settings()

    assert settings.app.port == 9911
    assert settings.services.whisper_model == "medium"


def test_load_settings_uses_bundled_config_when_frozen(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bundled_root = tmp_path / "bundle"
    _write_yaml(
        bundled_root / "config" / "default.yaml",
        "app:\n"
        "  port: 9922\n"
        "services:\n"
        "  whisper_model: large-v3\n",
    )

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundled_root), raising=False)

    settings = load_settings()

    assert settings.app.port == 9922
    assert settings.services.whisper_model == "large-v3"
