"""Whisper transcription service (local)."""

from __future__ import annotations

import ctypes
import logging
import threading
import wave
from collections.abc import Callable
from pathlib import Path

from diaricat.errors import DiaricatError, ErrorCode
from diaricat.models.domain import DeviceMode, RawTranscriptSegment
from diaricat.settings import Settings
from diaricat.utils.device import select_asr_runtime_device

logger = logging.getLogger(__name__)

WhisperProgressCallback = Callable[[float], None]
CancellationCheck = Callable[[], bool]

_WHISPER_MODEL_MIN_RAM_GB: dict[str, float] = {
    "tiny": 1.0,
    "base": 2.0,
    "small": 4.0,
    "medium": 8.0,
    "large-v2": 12.0,
    "large-v3": 12.0,
}
_WHISPER_MODEL_ORDER = ("tiny", "base", "small", "medium", "large-v2", "large-v3")


class WhisperTranscriptionService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model_cache: dict[str, object] = {}
        self._model_lock = threading.Lock()

    @staticmethod
    def _wav_duration(audio_path: Path) -> float:
        try:
            with wave.open(str(audio_path), "rb") as wav:
                frames = wav.getnframes()
                framerate = wav.getframerate()
            return float(frames) / float(framerate) if framerate > 0 else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _available_ram_gb() -> float | None:
        if ctypes is None:  # pragma: no cover
            return None

        if hasattr(ctypes, "windll"):  # Windows fast-path
            try:
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
                return round(float(stat.ullAvailPhys) / (1024**3), 2)
            except Exception:
                pass

        try:
            import psutil  # type: ignore

            return round(float(psutil.virtual_memory().available) / (1024**3), 2)
        except Exception:
            return None

    def _model_candidates(self) -> list[str]:
        requested = (self.settings.services.whisper_model or "small").strip().lower()
        if requested not in _WHISPER_MODEL_ORDER:
            requested = "small"

        candidates: list[str] = [requested]
        available = self._available_ram_gb()
        min_required = _WHISPER_MODEL_MIN_RAM_GB.get(requested)
        if available is None or min_required is None or available >= min_required:
            return candidates

        request_idx = _WHISPER_MODEL_ORDER.index(requested)
        for fallback_idx in range(request_idx - 1, -1, -1):
            candidate = _WHISPER_MODEL_ORDER[fallback_idx]
            needed = _WHISPER_MODEL_MIN_RAM_GB.get(candidate, 0.0)
            if available >= needed and candidate not in candidates:
                candidates.append(candidate)

        # Always include the smallest option as last resort.
        if "tiny" not in candidates:
            candidates.append("tiny")
        logger.warning(
            "Whisper model downgraded due to available RAM.",
            extra={
                "ctx_requested_model": requested,
                "ctx_available_ram_gb": available,
                "ctx_min_required_gb": min_required,
                "ctx_model_candidates": candidates,
            },
        )
        return candidates

    def _compute_type_candidates(self, runtime_device: str) -> list[str]:
        requested = (self.settings.services.whisper_compute_type or "int8").strip().lower()
        if not requested:
            requested = "int8"

        candidates = [requested]
        if runtime_device == "cpu":
            candidates.extend(["int8", "float32"])
        else:
            candidates.extend(["float16", "int8_float16", "int8"])

        deduped: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in deduped:
                deduped.append(candidate)
        return deduped

    def _load_model(self, model_name: str, runtime_device: str) -> tuple[object, str]:
        requested_compute = (self.settings.services.whisper_compute_type or "int8").strip().lower()
        candidates = self._compute_type_candidates(runtime_device)

        with self._model_lock:
            for compute_type in candidates:
                key = f"{model_name}:{runtime_device}:{compute_type}"
                cached = self._model_cache.get(key)
                if cached is not None:
                    return cached, compute_type

            try:
                from faster_whisper import WhisperModel  # type: ignore
            except Exception as exc:
                raise DiaricatError(
                    ErrorCode.ASR_ERROR,
                    "faster-whisper is not available. Install CPU/GPU extras first.",
                    details=str(exc),
                    failure_component="asr_dependency",
                    error_hint="Install/ship faster-whisper and ctranslate2 binaries in the runtime image.",
                ) from exc

            errors: list[str] = []
            for compute_type in candidates:
                key = f"{model_name}:{runtime_device}:{compute_type}"
                try:
                    model = WhisperModel(
                        model_name,
                        device=runtime_device,
                        compute_type=compute_type,
                        cpu_threads=self.settings.services.whisper_cpu_threads,
                    )
                    self._model_cache[key] = model
                    if compute_type != requested_compute:
                        logger.warning(
                            "Whisper compute_type '%s' is not compatible on %s. Falling back to '%s'.",
                            requested_compute,
                            runtime_device,
                            compute_type,
                        )
                    return model, compute_type
                except Exception as exc:
                    errors.append(f"{compute_type}: {exc}")

            details = " | ".join(errors)
            raise DiaricatError(
                ErrorCode.ASR_ERROR,
                "Failed to initialize Whisper model.",
                details=details,
                failure_component="asr_model_init",
                error_hint="Try a smaller model or CPU compute type.",
            )

    @staticmethod
    def _split_wav_into_chunks(
        audio_path: Path, chunk_seconds: int, overlap_seconds: int = 2,
    ) -> list[tuple[Path, float, float]]:
        with wave.open(str(audio_path), "rb") as src:
            channels = src.getnchannels()
            sample_width = src.getsampwidth()
            frame_rate = src.getframerate()
            total_frames = src.getnframes()
            chunk_frames = int(chunk_seconds * frame_rate)
            overlap_frames = int(overlap_seconds * frame_rate)

            if chunk_frames <= 0 or total_frames <= chunk_frames:
                duration = float(total_frames) / float(frame_rate) if frame_rate > 0 else 0.0
                return [(audio_path, 0.0, duration)]

            chunks_dir = audio_path.parent / "__asr_chunks"
            chunks_dir.mkdir(parents=True, exist_ok=True)
            out: list[tuple[Path, float, float]] = []
            frame_cursor = 0
            chunk_index = 0
            step_frames = max(chunk_frames - overlap_frames, chunk_frames // 2)
            while frame_cursor < total_frames:
                remaining = total_frames - frame_cursor
                take = min(chunk_frames, remaining)
                src.setpos(frame_cursor)
                payload = src.readframes(take)

                chunk_path = chunks_dir / f"chunk_{chunk_index:04d}.wav"
                with wave.open(str(chunk_path), "wb") as dst:
                    dst.setnchannels(channels)
                    dst.setsampwidth(sample_width)
                    dst.setframerate(frame_rate)
                    dst.writeframes(payload)

                start_s = float(frame_cursor) / float(frame_rate)
                end_s = float(frame_cursor + take) / float(frame_rate)
                out.append((chunk_path, start_s, end_s - start_s))
                frame_cursor += step_frames
                chunk_index += 1
            return out

    # Spanish initial prompt helps Whisper produce better punctuation and fewer
    # hallucinations on Spanish audio.  Kept short to avoid biasing the decoder.
    _INITIAL_PROMPTS: dict[str, str] = {
        "es": "Transcripción de una conversación en español con múltiples participantes.",
        "en": "Transcript of a conversation in English with multiple speakers.",
    }

    @staticmethod
    def _deduplicate_overlap_segments(
        segments: list[RawTranscriptSegment],
    ) -> list[RawTranscriptSegment]:
        """Remove near-duplicate segments produced by overlapping chunk windows."""
        if len(segments) <= 1:
            return segments
        # Sort by start time first
        segments.sort(key=lambda s: s.start)
        deduplicated: list[RawTranscriptSegment] = [segments[0]]
        for seg in segments[1:]:
            prev = deduplicated[-1]
            # If this segment overlaps significantly with the previous one and has
            # very similar text, skip it (it came from the overlap region).
            time_overlap = max(0.0, prev.end - seg.start)
            if time_overlap > 0.3:
                # Check text similarity: if the texts share a long common prefix
                # or are nearly identical, keep only the longer one.
                prev_words = prev.text.lower().split()
                seg_words = seg.text.lower().split()
                common = 0
                for pw, sw in zip(prev_words, seg_words):
                    if pw == sw:
                        common += 1
                    else:
                        break
                similarity = common / max(len(prev_words), len(seg_words), 1)
                if similarity > 0.5:
                    # Keep whichever segment is longer (more complete)
                    if len(seg.text) > len(prev.text):
                        deduplicated[-1] = seg
                    continue
            deduplicated.append(seg)
        return deduplicated

    def _transcribe_file(
        self,
        model: object,
        audio_path: Path,
        language: str | None,
        base_offset_s: float,
        on_segment: WhisperProgressCallback | None,
        is_cancelled: CancellationCheck | None,
    ) -> tuple[list[RawTranscriptSegment], str | None]:
        try:
            initial_prompt = self._INITIAL_PROMPTS.get(language or "", None)
            segments, info = model.transcribe(
                str(audio_path),
                language=language,
                vad_filter=True,
                beam_size=self.settings.services.whisper_beam_size,
                word_timestamps=True,
                initial_prompt=initial_prompt,
            )
            result: list[RawTranscriptSegment] = []
            detected_language = getattr(info, "language", None)
            for segment in segments:
                if is_cancelled is not None and is_cancelled():
                    raise DiaricatError(
                        ErrorCode.PIPELINE_ERROR,
                        "Pipeline cancelled by user.",
                        failure_component="asr_transcription",
                    )
                text = (segment.text or "").strip()
                if not text:
                    continue
                absolute_end = base_offset_s + float(segment.end)
                result.append(
                    RawTranscriptSegment(
                        start=base_offset_s + float(segment.start),
                        end=absolute_end,
                        text=text,
                    )
                )
                if on_segment is not None:
                    on_segment(absolute_end)
            return result, detected_language
        except DiaricatError:
            raise
        except Exception as exc:
            raise DiaricatError(
                ErrorCode.ASR_ERROR,
                "Whisper transcription failed.",
                details=str(exc),
                failure_component="asr_transcription",
                error_hint="Check model files and audio codec compatibility.",
            ) from exc

    def transcribe(
        self,
        audio_path: Path,
        language_hint: str,
        device_mode: DeviceMode,
        on_segment: WhisperProgressCallback | None = None,
        is_cancelled: CancellationCheck | None = None,
    ) -> tuple[list[RawTranscriptSegment], dict[str, object]]:
        requested_device = select_asr_runtime_device(device_mode)
        device_candidates = [requested_device]
        if requested_device == "cuda":
            device_candidates.append("cpu")
        logger.info(
            "ASR transcription started.",
            extra={
                "ctx_audio_path": str(audio_path),
                "ctx_requested_device": requested_device,
                "ctx_device_mode": str(device_mode.value),
                "ctx_whisper_model": self.settings.services.whisper_model,
                "ctx_whisper_compute_type": self.settings.services.whisper_compute_type,
                "ctx_chunk_seconds": int(self.settings.services.whisper_chunk_seconds),
                "ctx_beam_size": int(self.settings.services.whisper_beam_size),
            },
        )

        model_candidates = self._model_candidates()
        load_errors: list[str] = []
        model = None
        selected_model = None
        selected_device = None
        selected_compute = None
        fallbacks_applied: list[str] = []
        for runtime_device in device_candidates:
            for model_name in model_candidates:
                try:
                    model, compute_type = self._load_model(model_name, runtime_device)
                    selected_model = model_name
                    selected_device = runtime_device
                    selected_compute = compute_type
                    if model_name != self.settings.services.whisper_model:
                        fallbacks_applied.append(f"model:{self.settings.services.whisper_model}->{model_name}")
                    if runtime_device != requested_device:
                        fallbacks_applied.append(f"device:{requested_device}->{runtime_device}")
                    break
                except DiaricatError as exc:
                    load_errors.append(exc.details or exc.message)
            if model is not None:
                break

        if model is None or selected_model is None or selected_device is None or selected_compute is None:
            raise DiaricatError(
                ErrorCode.ASR_ERROR,
                "Failed to initialize any Whisper runtime candidate.",
                details=" | ".join(load_errors) if load_errors else None,
                failure_component="asr_model_init",
                error_hint="Try CPU mode or choose a smaller Whisper model in settings.",
            )
        logger.info(
            "ASR runtime selected.",
            extra={
                "ctx_selected_model": selected_model,
                "ctx_selected_device": selected_device,
                "ctx_selected_compute": selected_compute,
                "ctx_fallbacks_applied": fallbacks_applied,
            },
        )

        language = None if language_hint.lower() == "auto" else language_hint
        chunk_seconds = int(self.settings.services.whisper_chunk_seconds)
        duration_s = self._wav_duration(audio_path)
        chunk_items = self._split_wav_into_chunks(audio_path, chunk_seconds)
        logger.info(
            "ASR chunk plan prepared.",
            extra={
                "ctx_audio_path": str(audio_path),
                "ctx_chunk_count": len(chunk_items),
                "ctx_duration_s": duration_s,
            },
        )

        all_segments: list[RawTranscriptSegment] = []
        language_detected: str | None = None
        created_chunk_files: list[Path] = []
        try:
            for chunk_path, offset_s, _chunk_duration in chunk_items:
                if chunk_path != audio_path:
                    created_chunk_files.append(chunk_path)
                logger.debug(
                    "ASR processing chunk.",
                    extra={
                        "ctx_chunk_path": str(chunk_path),
                        "ctx_chunk_offset_s": round(offset_s, 3),
                        "ctx_chunk_duration_s": round(_chunk_duration, 3),
                    },
                )

                if is_cancelled is not None and is_cancelled():
                    raise DiaricatError(
                        ErrorCode.PIPELINE_ERROR,
                        "Pipeline cancelled by user.",
                        failure_component="asr_transcription",
                    )
                chunk_segments, detected = self._transcribe_file(
                    model=model,
                    audio_path=chunk_path,
                    language=language,
                    base_offset_s=offset_s,
                    on_segment=on_segment,
                    is_cancelled=is_cancelled,
                )
                all_segments.extend(chunk_segments)
                if language_detected is None and detected:
                    language_detected = str(detected)
        finally:
            for chunk_file in created_chunk_files:
                chunk_file.unlink(missing_ok=True)
            chunks_dir = audio_path.parent / "__asr_chunks"
            if chunks_dir.exists():
                try:
                    chunks_dir.rmdir()
                except OSError:
                    pass

        # Deduplicate segments from overlapping chunk regions.
        all_segments = self._deduplicate_overlap_segments(all_segments)

        if not all_segments:
            raise DiaricatError(
                ErrorCode.ASR_ERROR,
                "Whisper returned no transcription segments.",
                failure_component="asr_transcription",
                error_hint="Input might be silent or too noisy; try another model.",
            )

        metadata: dict[str, object] = {
            "language_detected": language_detected or (language or "auto"),
            "segment_count": len(all_segments),
            "duration_s": round(duration_s, 3),
            "chunk_count": len(chunk_items),
            "model_used": selected_model,
            "runtime_device": selected_device,
            "compute_type_used": selected_compute,
            "fallbacks_applied": fallbacks_applied,
        }
        logger.info(
            "ASR transcription completed.",
            extra={
                "ctx_audio_path": str(audio_path),
                "ctx_segment_count": len(all_segments),
                "ctx_language_detected": metadata["language_detected"],
                "ctx_chunk_count": metadata["chunk_count"],
                "ctx_model_used": metadata["model_used"],
                "ctx_runtime_device": metadata["runtime_device"],
                "ctx_compute_type_used": metadata["compute_type_used"],
                "ctx_fallbacks_applied": metadata["fallbacks_applied"],
            },
        )
        return all_segments, metadata
