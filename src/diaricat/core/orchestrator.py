"""Pipeline orchestration logic."""

from __future__ import annotations

import logging
import shutil
import wave
from collections.abc import Callable
from pathlib import Path
from time import monotonic, sleep

from diaricat.errors import DiaricatError, ErrorCode
from diaricat.models.domain import (
    ExportFormat,
    PipelineState,
    SummaryDocument,
    TranscriptDocument,
)
from diaricat.services.alignment_service import AlignmentService
from diaricat.services.audio_service import AudioService
from diaricat.services.diarization_service import PyannoteDiarizationService
from diaricat.services.export_service import ExportService
from diaricat.services.postprocess_service import LocalPostprocessService, PostprocessContext
from diaricat.services.transcription_service import WhisperTranscriptionService
from diaricat.utils.logging import log_pipeline_event
from diaricat.utils.paths import project_temp_dir

from .repository import ProjectRepository

ProgressCallback = Callable[[str, int], None]
CancellationCheck = Callable[[], bool]


class PipelineOrchestrator:
    def __init__(
        self,
        repository: ProjectRepository,
        audio_service: AudioService,
        transcription_service: WhisperTranscriptionService,
        diarization_service: PyannoteDiarizationService,
        alignment_service: AlignmentService,
        postprocess_service: LocalPostprocessService,
        export_service: ExportService,
    ) -> None:
        self.repository = repository
        self.audio_service = audio_service
        self.transcription_service = transcription_service
        self.diarization_service = diarization_service
        self.alignment_service = alignment_service
        self.postprocess_service = postprocess_service
        self.export_service = export_service
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _emit(progress: ProgressCallback | None, stage: str, value: int) -> None:
        if progress is not None:
            progress(stage, value)

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
    def _event_fields(base: dict[str, object], metadata: dict[str, object]) -> dict[str, object]:
        """Merge metadata into event fields without duplicate keyword collisions."""
        merged = dict(base)
        for key, value in metadata.items():
            if key in merged:
                merged[f"meta_{key}"] = value
            else:
                merged[key] = value
        return merged

    def _with_retry(self, operation: Callable[[], object], attempts: int = 2) -> object:
        non_retryable_components = {
            "asr_dependency",
            "asr_model_init",
            "diarization_dependency",
            "postprocess_dependency",
        }
        for idx in range(attempts):
            try:
                return operation()
            except DiaricatError as exc:
                exc.attempt = exc.attempt or (idx + 1)
                recoverable = {
                    ErrorCode.FFMPEG_ERROR,
                    ErrorCode.ASR_ERROR,
                    ErrorCode.DIARIZATION_ERROR,
                    ErrorCode.POSTPROCESS_ERROR,
                }
                if (
                    exc.code not in recoverable
                    or exc.failure_component in non_retryable_components
                    or idx == attempts - 1
                ):
                    raise
                self.logger.warning(
                    "Recoverable step failed, retrying",
                    extra={
                        "ctx_error_code": str(exc.code),
                        "ctx_attempt": idx + 1,
                        "ctx_failure_component": exc.failure_component,
                    },
                )
                sleep(0.2)
        raise DiaricatError(ErrorCode.PIPELINE_ERROR, "All retry attempts exhausted.")

    def _check_cancelled(self, is_cancelled: CancellationCheck | None) -> None:
        if is_cancelled is not None and is_cancelled():
            raise DiaricatError(ErrorCode.PIPELINE_ERROR, "Pipeline cancelled by user.")

    def _transcribe_with_compat(
        self,
        normalized_audio: Path,
        language_hint: str,
        device_mode,
        on_segment: Callable[[float], None],
        is_cancelled: CancellationCheck | None,
    ):
        try:
            return self.transcription_service.transcribe(
                normalized_audio,
                language_hint,
                device_mode,
                on_segment=on_segment,
                is_cancelled=is_cancelled,
            )
        except TypeError:
            # Backward compatibility for fake/legacy transcription services used in tests.
            return self.transcription_service.transcribe(
                normalized_audio,
                language_hint,
                device_mode,
            )

    def _cleanup_temp(self, project_id: str) -> None:
        try:
            temp_dir = project_temp_dir(self.repository.settings, project_id)
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            self.logger.warning("Failed to clean up temp files for project %s", project_id)

    def run_pipeline(
        self,
        project_id: str,
        run_correction: bool = True,
        run_summary: bool = True,
        progress: ProgressCallback | None = None,
        is_cancelled: CancellationCheck | None = None,
    ) -> dict[str, str]:
        project = self.repository.get_project(project_id)
        self.logger.info("Pipeline started", extra={"extra": {"project_id": project_id}})
        log_pipeline_event(
            self.logger,
            "started",
            project_id=project_id,
            stage="pipeline",
            run_correction=run_correction,
            run_summary=run_summary,
            device_mode=project.device_mode.value,
            language_hint=project.language_hint,
        )

        try:
            self._check_cancelled(is_cancelled)
            validating_t0 = monotonic()
            self._emit(progress, "validating", 3)
            source = self.audio_service.validate(project.source_path)
            self.repository.set_state(project_id, PipelineState.VALIDATED)
            self._emit(progress, "validating", 8)
            log_pipeline_event(
                self.logger,
                "stage_completed",
                project_id=project_id,
                stage="validating",
                elapsed_ms=int((monotonic() - validating_t0) * 1000),
                source_path=project.source_path,
            )

            self._check_cancelled(is_cancelled)
            audio_t0 = monotonic()
            self._emit(progress, "audio", 8)
            normalized_audio = self._with_retry(lambda: self.audio_service.normalize_to_wav(project_id, source))
            self.repository.set_state(project_id, PipelineState.AUDIO_READY)
            self.repository.add_artifacts(project_id, {"normalized_audio": str(normalized_audio)})
            self._emit(progress, "audio", 22)
            log_pipeline_event(
                self.logger,
                "stage_completed",
                project_id=project_id,
                stage="audio",
                elapsed_ms=int((monotonic() - audio_t0) * 1000),
                normalized_audio=str(normalized_audio),
            )

            self._check_cancelled(is_cancelled)
            transcription_t0 = monotonic()
            self._emit(progress, "transcription", 22)
            audio_duration = self._wav_duration(normalized_audio)

            def _on_segment(segment_end: float) -> None:
                if audio_duration > 0:
                    pct = 22 + int((segment_end / audio_duration) * 33)
                    self._emit(progress, "transcription", min(pct, 55))

            asr_segments = self._with_retry(
                lambda: self._transcribe_with_compat(
                    normalized_audio=normalized_audio,
                    language_hint=project.language_hint,
                    device_mode=project.device_mode,
                    on_segment=_on_segment,
                    is_cancelled=is_cancelled,
                )
            )
            asr_metadata: dict[str, object] = {}
            if isinstance(asr_segments, tuple):
                asr_segments, asr_metadata = asr_segments
            self.repository.set_state(project_id, PipelineState.TRANSCRIBED)
            self._emit(progress, "transcription", 55)
            transcription_fields = self._event_fields(
                {"asr_segment_count": len(asr_segments)},
                asr_metadata,
            )
            log_pipeline_event(
                self.logger,
                "stage_completed",
                project_id=project_id,
                stage="transcription",
                elapsed_ms=int((monotonic() - transcription_t0) * 1000),
                **transcription_fields,
            )

            self._check_cancelled(is_cancelled)
            diarization_t0 = monotonic()
            self._emit(progress, "diarization", 55)
            speaker_turns = self._with_retry(
                lambda: self.diarization_service.diarize(normalized_audio, project.device_mode)
            )
            diarization_metadata = (
                self.diarization_service.get_last_metadata()
                if hasattr(self.diarization_service, "get_last_metadata")
                else {}
            )
            self.repository.set_state(project_id, PipelineState.DIARIZED)
            self._emit(progress, "diarization", 72)
            diarization_fields = self._event_fields(
                {"speaker_turn_count": len(speaker_turns)},
                diarization_metadata,
            )
            log_pipeline_event(
                self.logger,
                "stage_completed",
                project_id=project_id,
                stage="diarization",
                elapsed_ms=int((monotonic() - diarization_t0) * 1000),
                **diarization_fields,
            )

            self._check_cancelled(is_cancelled)
            merge_t0 = monotonic()
            self._emit(progress, "merge", 72)
            merged_segments = self.alignment_service.align(asr_segments, speaker_turns)
            profiles = self.alignment_service.build_speaker_profiles(merged_segments)
            transcript = TranscriptDocument(
                segments=merged_segments,
                full_text_raw=" ".join(seg.text_raw for seg in merged_segments).strip(),
                quality_metadata={
                    "asr_segment_count": len(asr_segments),
                    "speaker_turn_count": len(speaker_turns),
                    **asr_metadata,
                    **diarization_metadata,
                },
                speaker_profiles=profiles,
            )
            self.repository.save_transcript(project_id, transcript)
            self.repository.set_state(project_id, PipelineState.MERGED)
            self._emit(progress, "merge", 80)
            log_pipeline_event(
                self.logger,
                "stage_completed",
                project_id=project_id,
                stage="merge",
                elapsed_ms=int((monotonic() - merge_t0) * 1000),
                merged_segment_count=len(merged_segments),
                speaker_profile_count=len(profiles),
            )

            if run_correction:
                self._check_cancelled(is_cancelled)
                correction_t0 = monotonic()
                self._emit(progress, "correction", 80)
                self.correct_project(project_id)
                self._emit(progress, "correction", 90)
                log_pipeline_event(
                    self.logger,
                    "stage_completed",
                    project_id=project_id,
                    stage="correction",
                    elapsed_ms=int((monotonic() - correction_t0) * 1000),
                )

            if run_summary:
                self._check_cancelled(is_cancelled)
                summary_t0 = monotonic()
                self._emit(progress, "summary", 90)
                self.summarize_project(project_id)
                self._emit(progress, "summary", 97)
                log_pipeline_event(
                    self.logger,
                    "stage_completed",
                    project_id=project_id,
                    stage="summary",
                    elapsed_ms=int((monotonic() - summary_t0) * 1000),
                )

            self._emit(progress, "done", 100)
            log_pipeline_event(self.logger, "completed", project_id=project_id, stage="done")
            return {"project_id": project_id, "state": self.repository.get_project(project_id).pipeline_state.value}

        except DiaricatError as exc:
            log_pipeline_event(
                self.logger,
                "failed",
                project_id=project_id,
                stage="failed",
                error_code=str(exc.code),
                failure_component=exc.failure_component,
                error_hint=exc.error_hint,
                attempt=exc.attempt,
            )
            self.repository.set_state(
                project_id,
                PipelineState.FAILED,
                str(exc.code),
                exc.details or exc.message,
                failure_component=exc.failure_component,
                error_hint=exc.error_hint,
                attempt=exc.attempt,
            )
            raise
        except Exception as exc:
            log_pipeline_event(
                self.logger,
                "failed",
                project_id=project_id,
                stage="failed",
                error_code=str(ErrorCode.PIPELINE_ERROR),
                failure_component="orchestrator",
                error_hint="Unexpected error while running pipeline.",
            )
            self.repository.set_state(
                project_id,
                PipelineState.FAILED,
                str(ErrorCode.PIPELINE_ERROR),
                str(exc),
                failure_component="orchestrator",
                error_hint="Unexpected error while running pipeline.",
            )
            raise DiaricatError(
                ErrorCode.PIPELINE_ERROR,
                "Unexpected pipeline execution error.",
                details=str(exc),
                failure_component="orchestrator",
                error_hint="Unexpected error while running pipeline.",
            ) from exc
        finally:
            self._cleanup_temp(project_id)

    def correct_project(self, project_id: str) -> TranscriptDocument:
        project = self.repository.get_project(project_id)
        transcript = self.repository.get_transcript(project_id)

        corrected_segments = []
        speaker_history: dict[str, list[str]] = {}
        for seg in transcript.segments:
            history = speaker_history.get(seg.speaker_id, [])
            context_text = " ".join(history[-3:]).strip()
            corrected = self.postprocess_service.correct(
                seg.text_raw,
                context=PostprocessContext(
                    project_id=project_id,
                    language_hint=project.language_hint,
                    speaker_id=seg.speaker_id,
                    speaker_context=context_text if context_text else None,
                ),
            )
            seg.text_corrected = corrected
            corrected_segments.append(seg)
            speaker_history.setdefault(seg.speaker_id, []).append(corrected)

        transcript.segments = corrected_segments
        transcript.full_text_corrected = " ".join(seg.text_corrected or seg.text_raw for seg in corrected_segments).strip()
        self.repository.save_transcript(project_id, transcript)
        self.repository.set_state(project_id, PipelineState.CORRECTED)
        log_pipeline_event(
            self.logger,
            "stage_completed",
            project_id=project_id,
            stage="correction",
            corrected_segment_count=len(corrected_segments),
        )
        return transcript

    def summarize_project(self, project_id: str) -> SummaryDocument:
        project = self.repository.get_project(project_id)
        transcript = self.repository.get_transcript(project_id)
        summary_source = transcript.full_text_corrected or transcript.full_text_raw
        lang = project.language_hint if project.language_hint != "auto" else "es"
        try:
            summary = self.postprocess_service.summarize(summary_source, segments=transcript.segments, language=lang)
        except TypeError:
            summary = self.postprocess_service.summarize(summary_source)
        self.repository.save_summary(project_id, summary)
        self.repository.set_state(project_id, PipelineState.SUMMARIZED)
        log_pipeline_event(
            self.logger,
            "stage_completed",
            project_id=project_id,
            stage="summary",
            key_points=len(summary.key_points),
            decisions=len(summary.decisions),
            topics=len(summary.topics),
            citations=len(summary.citations or []),
        )
        return summary

    def rename_speakers(self, project_id: str, mapping: dict[str, str]) -> TranscriptDocument:
        transcript = self.repository.get_transcript(project_id)
        for segment in transcript.segments:
            if segment.speaker_id in mapping:
                segment.speaker_name = mapping[segment.speaker_id]

        for profile in transcript.speaker_profiles:
            if profile.speaker_id in mapping:
                profile.custom_name = mapping[profile.speaker_id]

        self.repository.save_transcript(project_id, transcript)
        self.repository.save_speaker_map(project_id, mapping)
        return transcript

    def export_project(
        self,
        project_id: str,
        formats: list[ExportFormat],
        include_timestamps: bool,
    ) -> dict[str, str]:
        project = self.repository.get_project(project_id)
        transcript = self.repository.get_transcript(project_id)
        summary = self.repository.get_summary(project_id)
        artifacts = self.export_service.export(project, transcript, summary, formats, include_timestamps)
        self.repository.add_artifacts(project_id, artifacts)
        self.repository.set_state(project_id, PipelineState.EXPORTED)
        return artifacts
