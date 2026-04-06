"""PyInstaller runtime hook: register torch DLL search paths.

In frozen onedir builds, torch's native extensions (_C.pyd) need their
companion DLLs (c10.dll, torch_cpu.dll, etc.) to be discoverable via
os.add_dll_directory and PATH.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


if getattr(sys, "frozen", False) and os.name == "nt":
    add_dll = getattr(os, "add_dll_directory", None)

    bundled_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    exe_root = Path(sys.executable).resolve().parent

    candidates = (
        bundled_root / "torch" / "lib",
        exe_root / "_internal" / "torch" / "lib",
        bundled_root / "ctranslate2",
    )
    for candidate in candidates:
        if candidate.is_dir():
            if callable(add_dll):
                add_dll(str(candidate))
            os.environ["PATH"] = str(candidate) + os.pathsep + os.environ.get("PATH", "")
