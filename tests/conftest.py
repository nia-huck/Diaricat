from __future__ import annotations

from pathlib import Path

import pytest

from diaricat.settings import AppConfig, DeviceConfig, ServicesConfig, Settings


@pytest.fixture()
def temp_settings(tmp_path: Path) -> Settings:
    return Settings(
        app=AppConfig(
            host="127.0.0.1",
            port=8765,
            workspace_dir=tmp_path / "workspace",
            temp_dir=tmp_path / "temp",
            log_dir=tmp_path / "logs",
        ),
        device=DeviceConfig(),
        services=ServicesConfig(
            llama_model_path=tmp_path / "models" / "postprocess.gguf",
        ),
    )
