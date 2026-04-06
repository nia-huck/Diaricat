from __future__ import annotations

import importlib

from typer.testing import CliRunner

cli_module = importlib.import_module("diaricat.cli.app")
from diaricat.core.repository import ProjectRepository
from diaricat.settings import AppConfig, DeviceConfig, ServicesConfig, Settings
from diaricat.utils.paths import ensure_runtime_dirs


class FakeContext:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        ensure_runtime_dirs(settings)
        self.repository = ProjectRepository(settings)


def test_cli_project_create_smoke(monkeypatch, tmp_path) -> None:
    settings = Settings(
        app=AppConfig(
            workspace_dir=tmp_path / "workspace",
            temp_dir=tmp_path / "temp",
            log_dir=tmp_path / "logs",
        ),
        device=DeviceConfig(),
        services=ServicesConfig(),
    )
    context = FakeContext(settings)
    monkeypatch.setattr(cli_module, "get_context", lambda: context)

    runner = CliRunner()
    result = runner.invoke(
        cli_module.app,
        [
            "project",
            "create",
            "--input",
            "C:/input/file.mp4",
            "--device",
            "cpu",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert "source_path" in result.stdout
