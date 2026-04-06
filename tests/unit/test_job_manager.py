from __future__ import annotations

import time

from diaricat.core.jobs import JobManager
from diaricat.errors import DiaricatError, ErrorCode
from diaricat.models.domain import JobStatus


def test_submit_is_idempotent_for_same_project_and_kind(temp_settings) -> None:
    manager = JobManager(temp_settings)
    manager.start()

    def task(progress):
        progress("running", 10)
        time.sleep(0.4)
        progress("running", 90)
        return {"ok": True}

    job1 = manager.submit("p1", "pipeline", task)
    job2 = manager.submit("p1", "pipeline", task)

    assert job1.job_id == job2.job_id

    time.sleep(0.7)
    result = manager.get(job1.job_id)
    assert result.status in {JobStatus.DONE, JobStatus.FAILED}
    manager.stop()


def test_failure_metadata_propagates_to_job_record(temp_settings) -> None:
    manager = JobManager(temp_settings)
    manager.start()

    def task(_progress):
        raise DiaricatError(
            ErrorCode.ASR_ERROR,
            "asr init failed",
            details="missing runtime dep",
            failure_component="asr_dependency",
            error_hint="install dependencies",
            attempt=1,
        )

    job = manager.submit("p2", "pipeline", task)
    time.sleep(0.4)
    result = manager.get(job.job_id)

    assert result.status == JobStatus.FAILED
    assert result.failure_component == "asr_dependency"
    assert result.error_hint == "install dependencies"
    assert result.attempt == 1
    manager.stop()
