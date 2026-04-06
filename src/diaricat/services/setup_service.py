"""System detection and model management for first-run setup."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import uuid
import json
import shutil
import importlib
from importlib import metadata as importlib_metadata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from diaricat.utils.speechbrain_compat import ensure_speechbrain_runtime_compat

logger = logging.getLogger(__name__)

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ Model catalogues â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

WHISPER_MODELS: list[dict[str, Any]] = [
    {
        "id": "tiny",
        "label": "Tiny",
        "repo": "Systran/faster-whisper-tiny",
        "size_mb": 75,
        "quality": 1,
        "speed": 4,
        "min_ram_gb": 1,
        "description": "Ultrarápido, calidad básica",
    },
    {
        "id": "base",
        "label": "Base",
        "repo": "Systran/faster-whisper-base",
        "size_mb": 145,
        "quality": 2,
        "speed": 4,
        "min_ram_gb": 2,
        "description": "Rápido, adecuado para notas cortas",
    },
    {
        "id": "small",
        "label": "Small",
        "repo": "Systran/faster-whisper-small",
        "size_mb": 466,
        "quality": 3,
        "speed": 3,
        "min_ram_gb": 4,
        "description": "Equilibrio ideal",
    },
    {
        "id": "medium",
        "label": "Medium",
        "repo": "Systran/faster-whisper-medium",
        "size_mb": 1530,
        "quality": 4,
        "speed": 2,
        "min_ram_gb": 8,
        "description": "Alta calidad, más lento",
    },
    {
        "id": "large-v2",
        "label": "Large v2",
        "repo": "Systran/faster-whisper-large-v2",
        "size_mb": 3100,
        "quality": 5,
        "speed": 1,
        "min_ram_gb": 12,
        "description": "Máxima precisión",
    },
    {
        "id": "large-v3",
        "label": "Large v3",
        "repo": "Systran/faster-whisper-large-v3",
        "size_mb": 3100,
        "quality": 5,
        "speed": 1,
        "min_ram_gb": 12,
        "description": "Máxima precisión, versión más reciente",
    },
]

LLM_MODELS: list[dict[str, Any]] = [
    {
        "id": "none",
        "label": "Sin modelo LLM",
        "repo": None,
        "filename": None,
        "size_mb": 0,
        "quality": 0,
        "min_ram_gb": 0,
        "description": "Sin corrección ni resumen IA",
    },
    {
        "id": "qwen2.5-1.5b",
        "label": "Qwen 2.5 · 1.5B",
        "repo": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "size_mb": 986,
        "quality": 2,
        "min_ram_gb": 4,
        "description": "Rápido, corrección básica",
    },
    {
        "id": "qwen2.5-3b",
        "label": "Qwen 2.5 · 3B",
        "repo": "Qwen/Qwen2.5-3B-Instruct-GGUF",
        "filename": "qwen2.5-3b-instruct-q4_k_m.gguf",
        "size_mb": 1930,
        "quality": 3,
        "min_ram_gb": 6,
        "description": "Equilibrio corrección/velocidad",
    },
    {
        "id": "qwen2.5-7b",
        "label": "Qwen 2.5 · 7B",
        "repo": "Qwen/Qwen2.5-7B-Instruct-GGUF",
        "filename": "qwen2.5-7b-instruct-q4_k_m.gguf",
        "fallback_filenames": ["qwen2.5-7b-instruct-q3_k_m.gguf"],
        "size_mb": 4680,
        "quality": 4,
        "min_ram_gb": 10,
        "description": "Alta calidad, resúmenes detallados",
    },
]

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ In-memory download tracker â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_llm_model(model_id: str) -> dict[str, Any] | None:
    return next((m for m in LLM_MODELS if m["id"] == model_id), None)


def llm_candidate_filenames(model: dict[str, Any]) -> list[str]:
    names: list[str] = []
    primary = str(model.get("filename") or "").strip()
    if primary:
        names.append(primary)
    for fallback in model.get("fallback_filenames", []):
        candidate = str(fallback or "").strip()
        if candidate and candidate not in names:
            names.append(candidate)
    return names


def find_existing_llm_path(model: dict[str, Any], dest_dir: Path) -> Path | None:
    for filename in llm_candidate_filenames(model):
        candidate = dest_dir / filename
        if is_llm_present(candidate):
            return candidate

    primary = str(model.get("filename") or "").strip()
    if not primary:
        return None

    stem_prefix = Path(primary).stem.split("-q", maxsplit=1)[0]
    if not stem_prefix:
        return None

    for candidate in sorted(dest_dir.glob(f"{stem_prefix}*.gguf")):
        if is_llm_present(candidate):
            return candidate
    return None


def _pick_llm_repo_filename(model: dict[str, Any], hf_token: str | None) -> str:
    candidates = llm_candidate_filenames(model)
    if not candidates:
        raise ValueError(f"Model '{model.get('id', 'unknown')}' has no candidate filenames.")

    repo_id = str(model.get("repo") or "").strip()
    if not repo_id:
        raise ValueError("Model has no repository configured.")

    try:
        from huggingface_hub import list_repo_files  # type: ignore

        files = list(list_repo_files(repo_id, token=hf_token or None))
    except Exception:
        return candidates[0]

    if not files:
        return candidates[0]

    by_basename: dict[str, str] = {Path(fname).name: fname for fname in files}
    for filename in candidates:
        if filename in by_basename:
            return by_basename[filename]

    primary_prefix = Path(candidates[0]).stem.split("-q", maxsplit=1)[0]
    gguf_files = [fname for fname in files if fname.lower().endswith(".gguf")]
    matching = [fname for fname in gguf_files if Path(fname).stem.startswith(primary_prefix)]
    pool = matching or gguf_files
    if not pool:
        return candidates[0]

    quant_order = ("q4_k_m", "q4_0", "q5_k_m", "q5_0", "q3_k_m", "q8_0")

    def _score(name: str) -> tuple[int, int]:
        lowered = Path(name).name.lower()
        for idx, marker in enumerate(quant_order):
            if marker in lowered:
                return idx, len(lowered)
        return len(quant_order), len(lowered)

    return sorted(pool, key=_score)[0]


_downloads: dict[str, dict[str, Any]] = {}
_downloads_lock = threading.Lock()


def _set_download(download_id: str, **kwargs: Any) -> None:
    with _downloads_lock:
        if download_id in _downloads:
            _downloads[download_id].update(kwargs)


def _init_download(download_id: str) -> None:
    with _downloads_lock:
        _downloads[download_id] = {
            "status": "running",
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "error": None,
        }


def get_download_status(download_id: str) -> dict[str, Any] | None:
    with _downloads_lock:
        return dict(_downloads[download_id]) if download_id in _downloads else None


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ System detection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _get_ram_gb() -> float:
    """Best-effort total RAM in GB. Falls back to 8.0 on failure."""
    if os.name == "nt":
        try:
            import ctypes

            class _MEMSTATUS(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = _MEMSTATUS()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
            return round(stat.ullTotalPhys / (1024**3), 1)
        except Exception:
            pass

    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / (1024**2), 1)
    except Exception:
        pass

    try:
        import subprocess

        out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True, timeout=3)
        return round(int(out.strip()) / (1024**3), 1)
    except Exception:
        pass

    try:
        import psutil  # type: ignore

        return round(psutil.virtual_memory().total / (1024**3), 1)
    except Exception:
        pass

    return 8.0


def _get_gpu_info() -> dict[str, Any]:
    detected_gpu = None
    if os.name == "nt":
        detected_gpu = _get_nvidia_smi_gpu_info() or _get_windows_gpu_info()

    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            return {
                "detected": True,
                "available": True,
                "name": props.name,
                "vram_gb": round(props.total_memory / (1024**3), 1),
            }
    except Exception:
        pass

    if detected_gpu:
        return {
            "detected": True,
            "available": False,
            "name": detected_gpu["name"],
            "vram_gb": detected_gpu["vram_gb"],
        }

    return {"detected": False, "available": False, "name": None, "vram_gb": 0.0}


def _get_nvidia_smi_gpu_info() -> dict[str, Any] | None:
    """Query NVIDIA GPU name and VRAM when nvidia-smi is available."""
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
            startupinfo=startupinfo,
        ).strip()
    except Exception:
        return None

    if not output:
        return None

    first_line = output.splitlines()[0]
    parts = [part.strip() for part in first_line.split(",", maxsplit=1)]
    if not parts or not parts[0]:
        return None

    vram_gb = 0.0
    if len(parts) > 1:
        try:
            vram_gb = round(int(parts[1]) / 1024, 1)
        except ValueError:
            vram_gb = 0.0

    return {
        "name": parts[0],
        "vram_gb": vram_gb,
    }


def _get_windows_gpu_info() -> dict[str, Any] | None:
    """Return the most capable Windows GPU detected by WMI/CIM."""
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        output = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_VideoController | "
                "Select-Object Name,AdapterRAM | ConvertTo-Json -Compress",
            ],
            text=True,
            timeout=5,
            startupinfo=startupinfo,
        ).strip()
    except Exception:
        return None

    if not output:
        return None

    try:
        raw = json.loads(output)
    except json.JSONDecodeError:
        return None

    adapters = raw if isinstance(raw, list) else [raw]
    filtered: list[dict[str, Any]] = []
    for adapter in adapters:
        name = str(adapter.get("Name") or "").strip()
        if not name:
            continue
        lowered = name.lower()
        if "microsoft basic render" in lowered:
            continue

        adapter_ram = adapter.get("AdapterRAM")
        try:
            ram_bytes = int(adapter_ram) if adapter_ram is not None else 0
        except (TypeError, ValueError):
            ram_bytes = 0

        filtered.append(
            {
                "name": name,
                "ram_bytes": ram_bytes,
                "integrated": any(token in lowered for token in ("intel", "uhd", "iris", "vega")),
            }
        )

    if not filtered:
        return None

    best = max(filtered, key=lambda item: (not item["integrated"], item["ram_bytes"]))
    return {
        "name": best["name"],
        "vram_gb": round(best["ram_bytes"] / (1024**3), 1) if best["ram_bytes"] > 0 else 0.0,
    }


def detect_system() -> dict[str, Any]:
    ram_gb = _get_ram_gb()
    gpu = _get_gpu_info()
    return {
        "ram_gb": ram_gb,
        "cpu_cores": os.cpu_count() or 1,
        "has_gpu": gpu["detected"],
        "gpu_usable": gpu["available"],
        "gpu_name": gpu["name"],
        "gpu_vram_gb": gpu["vram_gb"],
    }


def _package_version(package_name: str) -> str | None:
    try:
        return importlib_metadata.version(package_name)
    except Exception:
        return None


def _diagnose_component(
    module_name: str,
    package_name: str,
    probe: Callable[[Any], None] | None = None,
    hint: str | None = None,
) -> dict[str, Any]:
    status: dict[str, Any] = {
        "ok": True,
        "version": None,
        "error_hint": None,
    }
    try:
        module = importlib.import_module(module_name)
        if probe is not None:
            probe(module)
        status["version"] = getattr(module, "__version__", None) or _package_version(package_name)
    except Exception as exc:
        status["ok"] = False
        reason = f"{exc.__class__.__name__}: {exc}"
        status["error_hint"] = f"{reason} | {hint}" if hint else reason
    return status


def _probe_speechbrain(module: Any) -> None:
    """
    Validate speechbrain package layout needed by EncoderClassifier.from_hparams.

    In PyInstaller onefile mode, runtime code in speechbrain expects a concrete
    package directory containing `dataio`. If this directory is missing, diarization
    silently degrades to spectral fallback.
    """
    package_file = Path(getattr(module, "__file__", "")).resolve()
    package_dir = package_file.parent
    dataio_dir = package_dir / "dataio"
    if not dataio_dir.exists() or not dataio_dir.is_dir():
        raise RuntimeError(f"speechbrain dataio package path missing: {dataio_dir}")


def _diagnose_speechbrain() -> dict[str, Any]:
    status: dict[str, Any] = {
        "ok": True,
        "version": None,
        "error_hint": None,
    }
    try:
        ensure_speechbrain_runtime_compat()
        module = importlib.import_module("speechbrain")
        _probe_speechbrain(module)
        status["version"] = getattr(module, "__version__", None) or _package_version("speechbrain")
    except Exception as exc:
        status["ok"] = False
        reason = f"{exc.__class__.__name__}: {exc}"
        status["error_hint"] = (
            f"{reason} | "
            "Packaged runtime must include speechbrain/dataio files and torchaudio compatibility shims."
        )
    return status


def runtime_diagnostics() -> dict[str, dict[str, Any]]:
    """Return runtime health information for core local inference dependencies."""

    return {
        "torch": _diagnose_component(
            module_name="torch",
            package_name="torch",
            probe=lambda module: module.cuda.is_available(),
            hint="Check bundled torch/lib DLLs and Visual C++ runtime.",
        ),
        "faster_whisper": _diagnose_component(
            module_name="faster_whisper",
            package_name="faster-whisper",
        ),
        "ctranslate2": _diagnose_component(
            module_name="ctranslate2",
            package_name="ctranslate2",
            probe=lambda module: module.get_cuda_device_count(),
        ),
        "speechbrain": _diagnose_speechbrain(),
        "llama_cpp": _diagnose_component(
            module_name="llama_cpp",
            package_name="llama-cpp-python",
        ),
    }


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ Recommendations â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def recommend_models(ram_gb: float, gpu_vram_gb: float, gpu_usable: bool = False) -> dict[str, str]:
    """Return the best whisper/llm model IDs the system can comfortably run."""
    effective = max(ram_gb, gpu_vram_gb * 1.5) if gpu_usable else ram_gb

    whisper_id = "tiny"
    for m in WHISPER_MODELS:
        if effective >= m["min_ram_gb"]:
            whisper_id = m["id"]

    llm_id = "none"
    for m in LLM_MODELS:
        if m["id"] == "none":
            continue
        if ram_gb >= m["min_ram_gb"]:
            llm_id = m["id"]

    return {"whisper": whisper_id, "llm": llm_id}


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ Cache checks â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _hf_cache_dir() -> Path:
    hf_home = os.environ.get("HF_HOME") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    if hf_home:
        return Path(hf_home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def is_whisper_cached(model_id: str) -> bool:
    model = next((m for m in WHISPER_MODELS if m["id"] == model_id), None)
    if not model:
        return False
    folder = "models--" + model["repo"].replace("/", "--")
    snapshots = _hf_cache_dir() / folder / "snapshots"
    try:
        return snapshots.exists() and any(snapshots.iterdir())
    except Exception:
        return False


def is_llm_present(model_path: Path) -> bool:
    return model_path.exists() and model_path.stat().st_size > 1024 * 1024


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ Downloads â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _download_file_streaming(
    url: str,
    dest: Path,
    token: str | None,
    on_progress: Callable[[int, int], None] | None,
) -> None:
    """Stream-download a file with byte-level progress tracking."""
    try:
        import requests  # type: ignore
    except ImportError:
        raise RuntimeError("requests package not available")

    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_suffix(dest.suffix + ".tmp")

    with requests.get(url, stream=True, headers=headers, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        with open(tmp_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    fh.write(chunk)
                    downloaded += len(chunk)
                    if on_progress:
                        on_progress(downloaded, total)

    tmp_path.replace(dest)


def start_whisper_download(model_id: str, hf_token: str | None = None) -> str:
    download_id = uuid.uuid4().hex
    _init_download(download_id)
    thread = threading.Thread(
        target=_run_whisper_download,
        args=(download_id, model_id, hf_token),
        daemon=True,
        name=f"dl-whisper-{model_id}",
    )
    thread.start()
    return download_id


def _run_whisper_download(download_id: str, model_id: str, hf_token: str | None) -> None:
    try:
        model = next((m for m in WHISPER_MODELS if m["id"] == model_id), None)
        if not model:
            raise ValueError(f"Unknown whisper model id: {model_id!r}")

        repo_id: str = model["repo"]
        total_mb: int = model["size_mb"]
        estimated_total = total_mb * 1024 * 1024

        _set_download(download_id, total_bytes=estimated_total, downloaded_bytes=0)

        try:
            from huggingface_hub import list_repo_files, list_repo_tree  # type: ignore

            files = list(list_repo_files(repo_id, token=hf_token or None))
            # Try to get real file sizes for accurate progress
            file_sizes: dict[str, int] = {}
            try:
                for info in list_repo_tree(repo_id, token=hf_token or None):
                    if hasattr(info, "size") and hasattr(info, "rfilename"):
                        file_sizes[info.rfilename] = info.size or 0
            except Exception:
                pass
            real_total = sum(file_sizes.values()) if file_sizes else estimated_total
            if real_total > 0:
                _set_download(download_id, total_bytes=real_total)
        except Exception:
            files = ["model.bin", "config.json", "tokenizer.json", "vocabulary.txt"]
            real_total = estimated_total

        n = max(len(files), 1)
        from huggingface_hub import hf_hub_download  # type: ignore

        downloaded_so_far = 0
        failed_files: list[str] = []
        for i, fname in enumerate(files):
            file_size = file_sizes.get(fname, real_total // n) if file_sizes else (real_total // n)
            # Report that we're starting this file
            _set_download(download_id, downloaded_bytes=downloaded_so_far, total_bytes=real_total)
            try:
                hf_hub_download(repo_id=repo_id, filename=fname, token=hf_token or None)
                downloaded_so_far += file_size
            except Exception as exc:
                logger.warning("Could not download %s/%s: %s", repo_id, fname, exc)
                failed_files.append(fname)
                downloaded_so_far += file_size  # still advance progress
            _set_download(download_id, downloaded_bytes=min(downloaded_so_far, real_total), total_bytes=real_total)

        if failed_files and len(failed_files) >= len(files):
            _set_download(
                download_id, status="failed",
                error=f"All files failed to download: {', '.join(failed_files[:3])}",
            )
        else:
            if failed_files:
                logger.warning("Whisper download completed with %d failed files: %s", len(failed_files), failed_files)
            _set_download(download_id, status="done", downloaded_bytes=real_total, total_bytes=real_total)
    except Exception as exc:
        logger.error("Whisper download failed: %s", exc)
        _set_download(download_id, status="failed", error=str(exc))


def start_llm_download(model_id: str, dest_dir: Path, hf_token: str | None = None) -> str:
    model = get_llm_model(model_id)
    if not model or not model["repo"] or not model["filename"]:
        raise ValueError(f"Unknown or non-downloadable LLM model id: {model_id!r}")

    download_id = uuid.uuid4().hex
    _init_download(download_id)
    thread = threading.Thread(
        target=_run_llm_download,
        args=(download_id, model, dest_dir, hf_token),
        daemon=True,
        name=f"dl-llm-{model_id}",
    )
    thread.start()
    return download_id


def _run_llm_download(
    download_id: str,
    model: dict[str, Any],
    dest_dir: Path,
    hf_token: str | None,
) -> None:
    try:
        repo_id: str = model["repo"]
        canonical_filename: str = model["filename"]
        repo_filename = _pick_llm_repo_filename(model, hf_token)
        dest = dest_dir / canonical_filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        expected_total = model["size_mb"] * 1024 * 1024
        _set_download(download_id, total_bytes=expected_total, downloaded_bytes=0)

        # Always use streaming download for LLM files so we get byte-level progress.
        # hf_hub_download doesn't report progress and the file is large (1-5 GB).
        url = f"https://huggingface.co/{repo_id}/resolve/main/{repo_filename}"

        def _on_bytes(downloaded: int, total: int) -> None:
            _set_download(download_id, downloaded_bytes=downloaded, total_bytes=total or expected_total)

        _download_file_streaming(url, dest, hf_token, _on_bytes)
        size = dest.stat().st_size if dest.exists() else expected_total
        _set_download(download_id, status="done", downloaded_bytes=size, total_bytes=size)

    except Exception as exc:
        logger.error("LLM download failed: %s", exc)
        _set_download(download_id, status="failed", error=str(exc))
