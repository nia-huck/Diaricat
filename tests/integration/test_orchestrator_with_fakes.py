from __future__ import annotations

from pathlib import Path

from diaricat.core.orchestrator import PipelineOrchestrator
from diaricat.core.repository import ProjectRepository
from diaricat.models.domain import DeviceMode, ExportFormat, RawTranscriptSegment, SpeakerTurn, SummaryDocument
from diaricat.services.alignment_service import AlignmentService
from diaricat.services.export_service import ExportService
from diaricat.utils.paths import ensure_runtime_dirs


class FakeAudioService:
    def __init__(self, audio_path: Path):
        self.audio_path = audio_path

    def validate(self, source_path: str) -> Path:
        return Path(source_path)

    def normalize_to_wav(self, project_id: str, source: Path) -> Path:
        return self.audio_path


class FakeTranscriptionService:
    def transcribe(self, audio_path: Path, language_hint: str, device_mode: DeviceMode):
        return [RawTranscriptSegment(start=0, end=2, text="hola mundo")]


class FakeDiarizationService:
    def diarize(self, audio_path: Path, device_mode: DeviceMode):
        return [SpeakerTurn(start=0, end=2, speaker_id="SPEAKER_00")]


class FakePostprocessService:
    def correct(self, text: str, context=None) -> str:
        return text + "."

    def summarize(self, text: str) -> SummaryDocument:
        return SummaryDocument(
            overview="overview",
            key_points=["kp1"],
            decisions=["dec1"],
            topics=["topic1"],
        )


def test_pipeline_and_export_with_fakes(temp_settings, tmp_path: Path) -> None:
    ensure_runtime_dirs(temp_settings)
    repo = ProjectRepository(temp_settings)

    source = tmp_path / "meeting.mp3"
    source.write_text("dummy", encoding="utf-8")

    normalized = tmp_path / "normalized.wav"
    normalized.write_text("dummy", encoding="utf-8")

    orchestrator = PipelineOrchestrator(
        repository=repo,
        audio_service=FakeAudioService(normalized),
        transcription_service=FakeTranscriptionService(),
        diarization_service=FakeDiarizationService(),
        alignment_service=AlignmentService(),
        postprocess_service=FakePostprocessService(),
        export_service=ExportService(temp_settings),
    )

    project = repo.create_project(str(source), DeviceMode.CPU)

    orchestrator.run_pipeline(project.id, run_correction=True, run_summary=True)
    transcript = repo.get_transcript(project.id)
    summary = repo.get_summary(project.id)

    assert transcript.full_text_corrected is not None
    assert summary is not None

    artifacts = orchestrator.export_project(
        project.id,
        [ExportFormat.JSON, ExportFormat.MD, ExportFormat.TXT, ExportFormat.PDF, ExportFormat.DOCX],
        True,
    )
    assert set(artifacts.keys()) == {"json", "md", "txt", "pdf", "docx"}
    for path in artifacts.values():
        assert Path(path).exists()
