"""Single-worker async job manager with persistent job records."""

from __future__ import annotations

import logging
import queue
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from diaricat.errors import DiaricatError, ErrorCode
from diaricat.models.domain import JobRecord, JobStatus
from diaricat.settings import Settings
from diaricat.utils.paths import atomic_write_json, jobs_dir, read_json

logger = logging.getLogger(__name__)
from diaricat.utils.logging import log_pipeline_event

ProgressFn = Callable[[str, int], None]
JobTask = Callable[[ProgressFn], dict[str, Any] | None]


class JobManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._jobs: dict[str, JobRecord] = {}
        self._tasks: dict[str, JobTask] = {}
        self._active: dict[tuple[str, str], str] = {}
        self._queue: queue.Queue[str] = queue.Queue()
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._jobs_dir = jobs_dir(settings)
        self._load_jobs()

    def _now(self) -> datetime:
        return datetime.now(tz=timezone.utc)

    def _job_path(self, job_id: str) -> Path:
        return self._jobs_dir / f"{job_id}.json"

    def _persist(self, job: JobRecord) -> None:
        atomic_write_json(self._job_path(job.job_id), job.model_dump(mode="json"))

    def _load_jobs(self) -> None:
        # Maximum number of finished job records to keep on disk.
        MAX_FINISHED_JOBS = 50

        all_jobs: list[JobRecord] = []
        for path in self._jobs_dir.glob("*.json"):
            try:
                job = JobRecord.model_validate(read_json(path))
                if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                    job.status = JobStatus.FAILED
                    job.stage = "interrupted"
                    job.error_code = str(ErrorCode.PIPELINE_ERROR)
                    job.error_detail = "Job interrupted by process restart."
                    job.failure_component = "job_manager"
                    job.error_hint = "Restart Diaricat and run the pipeline again."
                    job.ended_at = self._now()
                    self._persist(job)
                all_jobs.append(job)
            except Exception:
                logger.warning("Skipping corrupted job file: %s", path)
                # Remove corrupted files
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
                continue

        # Prune old finished jobs to prevent unbounded growth.
        finished = [j for j in all_jobs if j.status in {JobStatus.DONE, JobStatus.FAILED}]
        finished.sort(key=lambda j: j.ended_at or j.created_at, reverse=True)
        pruned_ids: set[str] = set()
        for old_job in finished[MAX_FINISHED_JOBS:]:
            pruned_ids.add(old_job.job_id)
            try:
                self._job_path(old_job.job_id).unlink(missing_ok=True)
            except Exception:
                pass

        for job in all_jobs:
            if job.job_id not in pruned_ids:
                self._jobs[job.job_id] = job

        if pruned_ids:
            logger.info("Pruned %d old job records.", len(pruned_ids))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker_loop, name="diaricat-job-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def submit(self, project_id: str, kind: str, task: JobTask) -> JobRecord:
        key = (project_id, kind)
        with self._lock:
            existing_id = self._active.get(key)
            if existing_id:
                existing = self._jobs.get(existing_id)
                if existing and existing.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                    return existing.model_copy()

            job = JobRecord(job_id=uuid.uuid4().hex, project_id=project_id, kind=kind)
            self._jobs[job.job_id] = job
            self._tasks[job.job_id] = task
            self._active[key] = job.job_id
            self._persist(job)
            self._queue.put(job.job_id)
            return job.model_copy()

    def cancel(self, job_id: str) -> JobRecord:
        with self._lock:
            if job_id not in self._jobs:
                raise DiaricatError(ErrorCode.NOT_FOUND, f"Job '{job_id}' not found")
            job = self._jobs[job_id]
            if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
                return job.model_copy()
            self._cancelled.add(job_id)
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.FAILED
                job.stage = "cancelled"
                job.error_code = "CANCELLED"
                job.error_detail = "Job cancelled by user."
                job.failure_component = "job_manager"
                job.ended_at = self._now()
                self._persist(job)
                key = (job.project_id, job.kind)
                if self._active.get(key) == job_id:
                    self._active.pop(key, None)
                self._tasks.pop(job_id, None)
            return job.model_copy()

    def is_cancelled(self, job_id: str) -> bool:
        return job_id in self._cancelled

    def get(self, job_id: str) -> JobRecord:
        with self._lock:
            if job_id not in self._jobs:
                raise DiaricatError(ErrorCode.NOT_FOUND, f"Job '{job_id}' not found")
            return self._jobs[job_id].model_copy()

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job_id = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            with self._lock:
                job = self._jobs[job_id]
                task = self._tasks.get(job_id)
                job.status = JobStatus.RUNNING
                job.stage = "running"
                job.started_at = self._now()
                self._persist(job)
            log_pipeline_event(logger, "started", project_id=job.project_id, stage="queued")

            if task is None:
                with self._lock:
                    job.status = JobStatus.FAILED
                    job.error_code = str(ErrorCode.PIPELINE_ERROR)
                    job.error_detail = "Missing job task"
                    job.failure_component = "job_manager"
                    job.error_hint = "Internal task reference was lost. Retry the operation."
                    job.ended_at = self._now()
                    self._persist(job)
                self._queue.task_done()
                continue

            def update_progress(stage: str, progress: int) -> None:
                with self._lock:
                    current = self._jobs[job_id]
                    current.stage = stage
                    current.progress = max(0, min(100, progress))
                    self._persist(current)

            try:
                import time as _time
                _t0 = _time.monotonic()
                result = task(update_progress) or {}
                elapsed_ms = int((_time.monotonic() - _t0) * 1000)
                log_pipeline_event(
                    logger,
                    "completed",
                    project_id=job.project_id,
                    stage=job.stage,
                    elapsed_ms=elapsed_ms,
                )
                with self._lock:
                    current = self._jobs[job_id]
                    current.status = JobStatus.DONE
                    current.stage = "done"
                    current.progress = 100
                    current.ended_at = self._now()
                    current.result = result
                    self._persist(current)
            except DiaricatError as exc:
                with self._lock:
                    current = self._jobs[job_id]
                    current.status = JobStatus.FAILED
                    current.stage = "failed"
                    current.ended_at = self._now()
                    current.error_code = str(exc.code)
                    current.error_detail = exc.details or exc.message
                    current.failure_component = exc.failure_component
                    current.error_hint = exc.error_hint
                    current.attempt = exc.attempt
                    self._persist(current)
                logger.exception(
                    "job_failed job_id=%s project=%s stage=%s error=%s",
                    job_id, job.project_id, job.stage, exc.details or exc.message,
                    extra={
                        "ctx_job_id": job_id,
                        "ctx_project_id": job.project_id,
                        "ctx_error_code": str(exc.code),
                        "ctx_failure_component": exc.failure_component,
                        "ctx_error_hint": exc.error_hint,
                        "ctx_attempt": exc.attempt,
                    },
                )
            except Exception as exc:
                with self._lock:
                    current = self._jobs[job_id]
                    current.status = JobStatus.FAILED
                    current.stage = "failed"
                    current.ended_at = self._now()
                    current.error_code = str(ErrorCode.PIPELINE_ERROR)
                    current.error_detail = str(exc)
                    current.failure_component = "job_manager"
                    current.error_hint = "Unexpected error in async worker."
                    self._persist(current)
                logger.exception(
                    "job_failed job_id=%s project=%s stage=%s error=%s",
                    job_id, job.project_id, job.stage, str(exc),
                    extra={
                        "ctx_job_id": job_id,
                        "ctx_project_id": job.project_id,
                        "ctx_error_code": str(ErrorCode.PIPELINE_ERROR),
                        "ctx_failure_component": "job_manager",
                        "ctx_error_hint": "Unexpected error in async worker.",
                    },
                )
            finally:
                with self._lock:
                    done = self._jobs[job_id]
                    key = (done.project_id, done.kind)
                    if self._active.get(key) == job_id:
                        self._active.pop(key, None)
                    self._tasks.pop(job_id, None)
                    self._cancelled.discard(job_id)
                self._queue.task_done()
