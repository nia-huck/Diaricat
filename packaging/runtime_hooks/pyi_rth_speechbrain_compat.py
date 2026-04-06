"""PyInstaller runtime hook: lazy-patch torchaudio.list_audio_backends.

torchaudio >=2.10 removed ``list_audio_backends()`` while speechbrain 1.0.x
still calls it at import time.  Instead of importing torchaudio eagerly here
(which can trigger torch circular-import issues), we install a lightweight
import hook that patches torchaudio the moment it finishes loading.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys


class _TorchaudioPatcher(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """One-shot meta-path hook: patches torchaudio after its real import."""

    _DONE = False

    def find_module(self, fullname, path=None):
        if fullname == "torchaudio" and not self._DONE:
            return self
        return None

    def load_module(self, fullname):
        # Remove ourselves so we don't recurse
        _TorchaudioPatcher._DONE = True
        if self in sys.meta_path:
            sys.meta_path.remove(self)

        # Let the real loader handle the import
        module = importlib.import_module(fullname)

        # Patch in the missing function
        if not hasattr(module, "list_audio_backends"):
            module.list_audio_backends = lambda: ["torchcodec"]

        return module


if getattr(sys, "frozen", False):
    sys.meta_path.insert(0, _TorchaudioPatcher())
