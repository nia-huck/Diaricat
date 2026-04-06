from __future__ import annotations

import pytest

from diaricat.models.domain import DeviceMode
from diaricat.utils import device


def test_auto_falls_back_to_cpu_when_no_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device, "torch_cuda_available", lambda: False)
    assert device.select_runtime_device(DeviceMode.AUTO) == "cpu"


def test_auto_uses_cuda_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device, "torch_cuda_available", lambda: True)
    assert device.select_runtime_device(DeviceMode.AUTO) == "cuda"


def test_force_gpu_without_cuda_falls_back_to_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device, "torch_cuda_available", lambda: False)
    assert device.select_runtime_device(DeviceMode.GPU) == "cpu"


def test_asr_auto_uses_cuda_when_ctranslate2_gpu_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device, "ctranslate2_cuda_available", lambda: True)
    assert device.select_asr_runtime_device(DeviceMode.AUTO) == "cuda"


def test_asr_gpu_falls_back_to_cpu_when_ctranslate2_gpu_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device, "ctranslate2_cuda_available", lambda: False)
    assert device.select_asr_runtime_device(DeviceMode.GPU) == "cpu"
