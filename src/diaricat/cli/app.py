"""Typer CLI for local operation and debugging."""

from __future__ import annotations

import json
import time
from pathlib import Path

import typer

from diaricat.bootstrap import get_context
from diaricat.errors import DiaricatError
from diaricat.models.domain import DeviceMode, ExportFormat, JobStatus

app = typer.Typer(help="Diaricat local CLI")
project_app = typer.Typer(help="Project commands")
pipeline_app = typer.Typer(help="Pipeline commands")
speakers_app = typer.Typer(help="Speaker commands")
export_app = typer.Typer(help="Export commands")
job_app = typer.Typer(help="Job commands")

app.add_typer(project_app, name="project")
app.add_typer(pipeline_app, name="pipeline")
app.add_typer(speakers_app, name="speakers")
app.add_typer(export_app, name="export")
app.add_typer(job_app, name="job")


def _print(payload: dict, as_json: bool = False) -> None:
    if as_json:
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    for k, v in payload.items():
        typer.echo(f"{k}: {v}")


def _handle_error(exc: DiaricatError) -> None:
    typer.echo(json.dumps(exc.to_dict(), ensure_ascii=False), err=True)
    raise typer.Exit(code=1)


@project_app.command("create")
def create_project(
    input: str = typer.Option(..., "--input", help="Input media file path"),
    device: DeviceMode = typer.Option(DeviceMode.AUTO, "--device"),
    language: str = typer.Option("auto", "--language"),
    as_json: bool = typer.Option(False, "--json", help="Print JSON output"),
) -> None:
    ctx = get_context()
    try:
        project = ctx.repository.create_project(input, device, language)
        _print(project.model_dump(mode="json"), as_json)
    except DiaricatError as exc:
        _handle_error(exc)


@pipeline_app.command("run")
def run_pipeline(
    project: str = typer.Option(..., "--project"),
    no_correct: bool = typer.Option(False, "--no-correct"),
    no_summary: bool = typer.Option(False, "--no-summary"),
    wait: bool = typer.Option(False, "--wait", help="Wait until job completion"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    ctx = get_context()
    try:
        job = ctx.jobs.submit(
            project_id=project,
            kind="pipeline",
            task=lambda progress: ctx.orchestrator.run_pipeline(
                project_id=project,
                run_correction=not no_correct,
                run_summary=not no_summary,
                progress=progress,
            ),
        )
        payload = job.model_dump(mode="json")
        _print(payload, as_json)

        if wait:
            while True:
                current = ctx.jobs.get(job.job_id)
                if current.status in {JobStatus.DONE, JobStatus.FAILED}:
                    _print(current.model_dump(mode="json"), as_json)
                    if current.status == JobStatus.FAILED:
                        raise typer.Exit(code=1)
                    return
                time.sleep(1)
    except DiaricatError as exc:
        _handle_error(exc)


@speakers_app.command("rename")
def rename_speakers(
    project: str = typer.Option(..., "--project"),
    map: Path = typer.Option(..., "--map", help="JSON file with {\"SPEAKER_00\": \"Name\"}"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    ctx = get_context()
    try:
        mapping = json.loads(map.read_text(encoding="utf-8"))
        transcript = ctx.orchestrator.rename_speakers(project, mapping)
        _print({"project_id": project, "updated_segments": len(transcript.segments)}, as_json)
    except DiaricatError as exc:
        _handle_error(exc)


@export_app.callback(invoke_without_command=True)
def export_project(
    ctx: typer.Context,
    project: str = typer.Option(..., "--project"),
    formats: str = typer.Option("json,md,txt", "--formats"),
    include_timestamps: bool = typer.Option(True, "--include-timestamps/--no-include-timestamps"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    if ctx.invoked_subcommand:
        return
    app_ctx = get_context()
    try:
        selected = [ExportFormat(fmt.strip().lower()) for fmt in formats.split(",") if fmt.strip()]
        artifacts = app_ctx.orchestrator.export_project(project, selected, include_timestamps)
        _print({"project_id": project, "artifacts": artifacts}, as_json)
    except DiaricatError as exc:
        _handle_error(exc)


@job_app.command("status")
def job_status(
    job: str = typer.Option(..., "--job"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    ctx = get_context()
    try:
        record = ctx.jobs.get(job)
        _print(record.model_dump(mode="json"), as_json)
    except DiaricatError as exc:
        _handle_error(exc)
