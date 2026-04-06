"""CPU/GPU selection helpers."""

from __future__ import annotations

import logging

from diaricat.models.domain import DeviceMode

logger = logging.getLogger(__name__)


def torch_cuda_available() -> bool:
    try:
        import torch  # type: ignore

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def ctranslate2_cuda_available() -> bool:
    try:
        import ctranslate2  # type: ignore

        return int(ctranslate2.get_cuda_device_count()) > 0
    except Exception:
        return False


def select_runtime_device(mode: DeviceMode) -> str:
    if mode == DeviceMode.CPU:
        return "cpu"

    gpu_ok = torch_cuda_available()
    if mode == DeviceMode.GPU:
        if not gpu_ok:
            logger.warning(
                "GPU mode was requested but no compatible CUDA device was detected. Falling back to CPU."
            )
            return "cpu"
        return "cuda"

    # AUTO mode: use GPU if available, otherwise continue on CPU.
    return "cuda" if gpu_ok else "cpu"


def select_asr_runtime_device(mode: DeviceMode) -> str:
    if mode == DeviceMode.CPU:
        return "cpu"

    gpu_ok = ctranslate2_cuda_available()
    if mode == DeviceMode.GPU:
        if not gpu_ok:
            logger.warning(
                "GPU mode was requested for ASR but no compatible CTranslate2 CUDA device was detected. "
                "Falling back to CPU."
            )
            return "cpu"
        return "cuda"
    return "cuda" if gpu_ok else "cpu"
