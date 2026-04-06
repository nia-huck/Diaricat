import json
import sys
from types import SimpleNamespace

import pytest

from diaricat.services import setup_service


def test_recommend_models_ignores_unusable_gpu():
    recommendation = setup_service.recommend_models(8.0, 6.0, gpu_usable=False)

    assert recommendation == {"whisper": "medium", "llm": "qwen2.5-3b"}


def test_recommend_models_uses_usable_gpu_vram():
    recommendation = setup_service.recommend_models(8.0, 6.0, gpu_usable=True)

    assert recommendation == {"whisper": "medium", "llm": "qwen2.5-3b"}


def test_get_windows_gpu_info_prefers_dedicated_adapter(monkeypatch):
    payload = json.dumps(
        [
            {"Name": "Intel(R) UHD Graphics", "AdapterRAM": 2147479552},
            {"Name": "NVIDIA GeForce RTX 3050 6GB Laptop GPU", "AdapterRAM": 6442450944},
        ]
    )

    monkeypatch.setattr(setup_service.subprocess, "check_output", lambda *args, **kwargs: payload)

    gpu = setup_service._get_windows_gpu_info()

    assert gpu == {
        "name": "NVIDIA GeForce RTX 3050 6GB Laptop GPU",
        "vram_gb": 6.0,
    }


def test_find_existing_llm_path_uses_fallback_filenames(tmp_path):
    model = {
        "id": "qwen2.5-7b",
        "filename": "qwen2.5-7b-instruct-q4_k_m.gguf",
        "fallback_filenames": ["qwen2.5-7b-instruct-q3_k_m.gguf"],
    }
    fallback = tmp_path / "qwen2.5-7b-instruct-q3_k_m.gguf"
    fallback.write_bytes(b"0" * (1024 * 1024 + 8))

    resolved = setup_service.find_existing_llm_path(model, tmp_path)

    assert resolved == fallback


def test_pick_llm_repo_filename_accepts_available_variant(monkeypatch):
    fake_hf = SimpleNamespace(
        list_repo_files=lambda repo_id, token=None: [  # noqa: ARG005
            "README.md",
            "qwen2.5-7b-instruct-q3_k_m.gguf",
        ]
    )
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hf)

    model = {
        "id": "qwen2.5-7b",
        "repo": "Qwen/Qwen2.5-7B-Instruct-GGUF",
        "filename": "qwen2.5-7b-instruct-q4_k_m.gguf",
        "fallback_filenames": ["qwen2.5-7b-instruct-q3_k_m.gguf"],
    }

    selected = setup_service._pick_llm_repo_filename(model, hf_token=None)

    assert selected == "qwen2.5-7b-instruct-q3_k_m.gguf"


def test_runtime_diagnostics_schema() -> None:
    diagnostics = setup_service.runtime_diagnostics()

    expected = {"torch", "faster_whisper", "ctranslate2", "speechbrain", "llama_cpp"}
    assert expected.issubset(set(diagnostics.keys()))
    for component in expected:
        status = diagnostics[component]
        assert isinstance(status.get("ok"), bool)
        assert "version" in status
        assert "error_hint" in status


def test_probe_speechbrain_detects_missing_dataio(tmp_path):
    fake_module = SimpleNamespace(__file__=str(tmp_path / "speechbrain" / "__init__.py"))

    with pytest.raises(RuntimeError, match="dataio"):
        setup_service._probe_speechbrain(fake_module)
