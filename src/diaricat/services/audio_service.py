"""Audio validation and normalization using ffmpeg/ffprobe."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from diaricat.errors import DiaricatError, ErrorCode
from diaricat.settings import Settings
from diaricat.utils.paths import project_temp_dir
from diaricat.utils.validation import validate_source_path


class AudioService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _candidate_ffmpeg_dirs() -> list[Path]:
        project_root = Path(__file__).resolve().parents[3]
        exe_root = Path(sys.executable).resolve().parent
        bundled_root = Path(getattr(sys, "_MEIPASS", exe_root))
        return [
            bundled_root / "vendor" / "ffmpeg",
            exe_root / "vendor" / "ffmpeg",
            project_root / "vendor" / "ffmpeg",
        ]

    def _resolve_bin(self, binary: str) -> str:
        ffmpeg_dir = self.settings.services.ffmpeg_bin_dir
        if ffmpeg_dir:
            candidate = Path(ffmpeg_dir) / (f"{binary}.exe" if not binary.endswith(".exe") else binary)
            if candidate.exists():
                return str(candidate)

        binary_name = f"{binary}.exe" if not binary.endswith(".exe") else binary
        for candidate_dir in self._candidate_ffmpeg_dirs():
            candidate = candidate_dir / binary_name
            if candidate.exists():
                return str(candidate)

        which_hit = shutil.which(binary_name) or shutil.which(binary)
        if which_hit:
            return which_hit

        return binary_name

    def validate(self, source_path: str) -> Path:
        source = validate_source_path(source_path)
        self._probe(source)
        return source

    def _probe(self, source: Path) -> None:
        ffprobe = self._resolve_bin("ffprobe")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        cmd = [
            ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-of",
            "json",
            str(source),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, creationflags=creationflags)
        except FileNotFoundError as exc:
            raise DiaricatError(
                ErrorCode.FFMPEG_ERROR,
                "ffprobe binary was not found.",
                details=f"Expected command: {ffprobe}",
            ) from exc
        if proc.returncode != 0:
            raise DiaricatError(
                ErrorCode.FFMPEG_ERROR,
                "ffprobe could not decode the input file.",
                details=proc.stderr.strip() or proc.stdout.strip(),
            )

        try:
            data = json.loads(proc.stdout or "{}")
            streams = data.get("streams", [])
        except Exception as exc:
            raise DiaricatError(ErrorCode.FFMPEG_ERROR, "Invalid ffprobe output", details=str(exc)) from exc

        has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
        if not has_audio:
            raise DiaricatError(ErrorCode.VALIDATION_ERROR, "Input file does not contain an audio stream.")

    def normalize_to_wav(self, project_id: str, source: Path) -> Path:
        temp_dir = project_temp_dir(self.settings, project_id)
        output = temp_dir / "normalized.wav"

        ffmpeg = self._resolve_bin("ffmpeg")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-vn",
            str(output),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, creationflags=creationflags)
        except FileNotFoundError as exc:
            raise DiaricatError(
                ErrorCode.FFMPEG_ERROR,
                "ffmpeg binary was not found.",
                details=f"Expected command: {ffmpeg}",
            ) from exc
        if proc.returncode != 0:
            raise DiaricatError(
                ErrorCode.FFMPEG_ERROR,
                "Failed to normalize input audio.",
                details=proc.stderr.strip() or proc.stdout.strip(),
            )
        if not output.exists() or output.stat().st_size == 0:
            raise DiaricatError(ErrorCode.FFMPEG_ERROR, "Normalized audio was not generated.")
        return output
