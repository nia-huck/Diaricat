from __future__ import annotations

from pathlib import Path

import pytest

from diaricat.errors import DiaricatError
from diaricat.utils.validation import validate_source_path


def test_accepts_supported_extension(tmp_path: Path) -> None:
    src = tmp_path / "sample.mp4"
    src.write_text("x", encoding="utf-8")
    assert validate_source_path(str(src)) == src


def test_rejects_unsupported_extension(tmp_path: Path) -> None:
    src = tmp_path / "sample.mov"
    src.write_text("x", encoding="utf-8")
    with pytest.raises(DiaricatError):
        validate_source_path(str(src))
