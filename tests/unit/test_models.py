from __future__ import annotations

from diaricat.models.domain import DeviceMode, PipelineState, Project


def test_project_serialization_roundtrip() -> None:
    project = Project(
        id="abc",
        source_path="C:/meeting.mp4",
        device_mode=DeviceMode.AUTO,
        pipeline_state=PipelineState.CREATED,
    )

    payload = project.model_dump(mode="json")
    reconstructed = Project.model_validate(payload)

    assert reconstructed.id == "abc"
    assert reconstructed.device_mode == DeviceMode.AUTO
    assert reconstructed.pipeline_state == PipelineState.CREATED
