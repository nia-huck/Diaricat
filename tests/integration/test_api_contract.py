from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from diaricat.api.app import create_app
from diaricat.bootstrap import AppContext
from diaricat.core.jobs import JobManager
from diaricat.core.repository import ProjectRepository
from diaricat.models.domain import (
    PipelineState,
    SummaryDocument,
    TranscriptDocument,
    TranscriptSegment,
)
from diaricat.settings import AppConfig, DeviceConfig, ServicesConfig, Settings
from diaricat.utils.paths import ensure_runtime_dirs


class FakeOrchestrator:
    def __init__(self, repository: ProjectRepository) -> None:
        self.repository = repository

    def run_pipeline(
        self,
        project_id: str,
        run_correction: bool,
        run_summary: bool,
        progress,
        is_cancelled=None,
    ):
        progress("validating", 25)
        progress("done", 100)
        self.repository.set_state(project_id, PipelineState.SUMMARIZED)
        return {"project_id": project_id, "state": "SUMMARIZED"}

    def correct_project(self, project_id: str):
        self.repository.set_state(project_id, PipelineState.CORRECTED)

    def summarize_project(self, project_id: str):
        self.repository.set_state(project_id, PipelineState.SUMMARIZED)

    def rename_speakers(self, project_id: str, mapping: dict[str, str]):
        raise NotImplementedError

    def export_project(self, project_id: str, formats, include_timestamps: bool):
        return {"json": "workspace/projects/x/exports/result.json"}


def _build_test_context(tmp_path: Path) -> AppContext:
    settings = Settings(
        app=AppConfig(
            workspace_dir=tmp_path / "workspace",
            temp_dir=tmp_path / "temp",
            log_dir=tmp_path / "logs",
        ),
        device=DeviceConfig(),
        services=ServicesConfig(),
    )
    ensure_runtime_dirs(settings)
    repository = ProjectRepository(settings)
    jobs = JobManager(settings)
    orchestrator = FakeOrchestrator(repository)
    return AppContext(settings=settings, repository=repository, orchestrator=orchestrator, jobs=jobs)


def test_create_project_and_run_job(tmp_path: Path) -> None:
    context = _build_test_context(tmp_path)
    app = create_app(context)

    with TestClient(app, base_url="http://localhost") as client:
        create_resp = client.post(
            "/v1/projects",
            json={"source_path": "C:/input/sample.mp4", "device_mode": "auto", "language_hint": "es"},
        )
        assert create_resp.status_code == 200
        project_id = create_resp.json()["id"]

        run_resp = client.post(f"/v1/projects/{project_id}/run", json={"run_correction": True, "run_summary": True})
        assert run_resp.status_code == 200
        job_id = run_resp.json()["job_id"]

        for _ in range(20):
            job_resp = client.get(f"/v1/jobs/{job_id}")
            assert job_resp.status_code == 200
            payload = job_resp.json()
            if payload["status"] in {"done", "failed"}:
                break
            time.sleep(0.05)

        assert payload["status"] == "done"


def test_transcript_and_summary_endpoints(tmp_path: Path) -> None:
    context = _build_test_context(tmp_path)
    app = create_app(context)

    with TestClient(app, base_url="http://localhost") as client:
        create_resp = client.post(
            "/v1/projects",
            json={"source_path": "C:/input/sample.mp4", "device_mode": "auto", "language_hint": "es"},
        )
        assert create_resp.status_code == 200
        project_id = create_resp.json()["id"]

        context.repository.save_transcript(
            project_id,
            TranscriptDocument(
                segments=[
                    TranscriptSegment(
                        start=0.0,
                        end=1.2,
                        speaker_id="SPEAKER_00",
                        speaker_name="Maria",
                        text_raw="hola",
                        text_corrected="hola.",
                    )
                ],
                full_text_raw="hola",
                full_text_corrected="hola.",
            ),
        )
        context.repository.save_summary(
            project_id,
            SummaryDocument(
                overview="overview",
                key_points=["k1"],
                decisions=["d1"],
                topics=["t1"],
            ),
        )

        transcript_resp = client.get(f"/v1/projects/{project_id}/transcript")
        assert transcript_resp.status_code == 200
        assert transcript_resp.json()["segments"][0]["speaker_id"] == "SPEAKER_00"

        summary_resp = client.get(f"/v1/projects/{project_id}/summary")
        assert summary_resp.status_code == 200
        assert summary_resp.json()["overview"] == "overview"


def test_upload_endpoint_persists_file(tmp_path: Path) -> None:
    context = _build_test_context(tmp_path)
    app = create_app(context)

    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/v1/system/upload",
            files={"file": ("meeting.mp4", b"fake-media-bytes", "video/mp4")},
        )

    assert response.status_code == 200
    payload = response.json()
    stored_path = Path(payload["stored_path"])
    assert stored_path.exists()
    assert stored_path.suffix == ".mp4"


def test_upload_endpoint_rejects_unknown_extension(tmp_path: Path) -> None:
    context = _build_test_context(tmp_path)
    app = create_app(context)

    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/v1/system/upload",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "VALIDATION_ERROR"


def test_system_diagnostics_endpoint(tmp_path: Path) -> None:
    context = _build_test_context(tmp_path)
    app = create_app(context)

    with TestClient(app, base_url="http://localhost") as client:
        response = client.get("/v1/system/diagnostics")

    assert response.status_code == 200
    payload = response.json()
    components = payload["components"]
    for key in ("torch", "faster_whisper", "ctranslate2", "speechbrain", "llama_cpp"):
        assert key in components
        assert "ok" in components[key]


def test_open_file_endpoint_uses_system_shell(tmp_path: Path, monkeypatch) -> None:
    context = _build_test_context(tmp_path)
    app = create_app(context)
    target = context.settings.app.workspace_dir / "result.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("ok", encoding="utf-8")

    opened: list[str] = []
    revealed: list[Path] = []
    if os.name == "nt":
        monkeypatch.setattr("diaricat.api.app._reveal_in_windows_explorer", lambda path: revealed.append(Path(path)))
    else:
        monkeypatch.setattr(os, "startfile", lambda path: opened.append(path))

    with TestClient(app, base_url="http://localhost") as client:
        response = client.post("/v1/system/open-file", json={"path": str(target)})

    assert response.status_code == 200
    if os.name == "nt":
        assert len(revealed) == 1
        assert revealed[0].resolve() == target.resolve()
    else:
        assert len(opened) == 1
        assert Path(opened[0]).resolve() == target.resolve()


def test_open_folder_endpoint_selects_file_in_explorer(tmp_path: Path, monkeypatch) -> None:
    context = _build_test_context(tmp_path)
    app = create_app(context)
    target = context.settings.app.workspace_dir / "result.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("ok", encoding="utf-8")

    captured: dict[str, object] = {}

    class DummyProc:
        pass

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return DummyProc()

    monkeypatch.setattr("diaricat.api.app.subprocess.Popen", fake_popen)

    with TestClient(app, base_url="http://localhost") as client:
        response = client.post("/v1/system/open-folder", json={"path": str(target)})

    assert response.status_code == 200
    command = captured["command"]
    assert isinstance(command, list)
    assert command[0].lower() == "explorer"
