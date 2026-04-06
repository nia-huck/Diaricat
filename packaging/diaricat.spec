# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec – Diaricat (onedir, production-ready).

Approach: let PyInstaller's automatic analysis discover torch/torchaudio
imports. Only add explicit collect_data_files / collect_dynamic_libs for
packages whose runtime data or native libs are missed by analysis.
Do NOT use collect_all('torch') — it over-collects and causes circular
import errors in the frozen environment.
"""

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

project_root = Path(SPEC).resolve().parents[1]

# ── pywebview hook path ──────────────────────────────────────────────────────
import webview as _wv

webview_hook_path = str(Path(_wv.__file__).parent / "__pyinstaller")

# ── Hidden imports ───────────────────────────────────────────────────────────
hiddenimports = []
hiddenimports += collect_submodules("diaricat")
hiddenimports += collect_submodules("webview")
hiddenimports += [
    "clr", "clr_loader", "pythonnet", "bottle", "proxy_tools",
    "engineio.async_drivers.threading",
]

# ── Data files ───────────────────────────────────────────────────────────────
extra_datas = []
extra_datas += collect_data_files("faster_whisper")
# SpeechBrain needs .py source files for hyperpyyaml dynamic class loading
extra_datas += collect_data_files("speechbrain", include_py_files=True)
extra_datas += collect_data_files("webview", subdir="js")
extra_datas += collect_data_files("webview", subdir="lib")

# ── Binaries (native shared libs) ───────────────────────────────────────────
extra_binaries = []
extra_binaries += collect_dynamic_libs("webview")

# ctranslate2 ships native DLLs that PyInstaller may miss
extra_binaries += collect_dynamic_libs("ctranslate2")
extra_datas += collect_data_files("ctranslate2")

# llama-cpp-python loads llama.dll at runtime
try:
    extra_binaries += collect_dynamic_libs("llama_cpp")
except Exception:
    pass

# ── Excludes ─────────────────────────────────────────────────────────────────
excludes = [
    "PyQt5", "PyQt6", "PySide2", "PySide6", "gi", "qtpy",
    "tkinter", "_tkinter",
    "pytest", "pytest_mock",
    "matplotlib", "IPython", "notebook", "jupyter",
]

block_cipher = None

a = Analysis(
    [str(project_root / "src" / "diaricat" / "main.py")],
    pathex=[str(project_root)],
    binaries=[
        (str(project_root / "vendor" / "ffmpeg" / "ffmpeg.exe"), "vendor/ffmpeg"),
        (str(project_root / "vendor" / "ffmpeg" / "ffprobe.exe"), "vendor/ffmpeg"),
    ] + extra_binaries,
    datas=[
        (str(project_root / "config" / "default.yaml"), "config"),
        (str(project_root / "docs" / "openapi-v1.md"), "docs"),
        (str(project_root / "docs" / "lovable-integration.md"), "docs"),
        (str(project_root / "frontend" / "dist"), "frontend_dist"),
        (str(project_root / "frontend" / "src" / "assets" / "diaricat-logo.png"), "assets"),
    ] + extra_datas,
    hiddenimports=hiddenimports,
    hookspath=[webview_hook_path],
    hooksconfig={},
    runtime_hooks=[
        str(project_root / "packaging" / "runtime_hooks" / "pyi_rth_torch_dll.py"),
        str(project_root / "packaging" / "runtime_hooks" / "pyi_rth_speechbrain_compat.py"),
    ],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
    module_collection_mode={},
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="Diarcat",
    icon=str(project_root / "assets" / "diarcat.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Diarcat",
)
