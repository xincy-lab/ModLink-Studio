from __future__ import annotations

import time
from pathlib import Path

import pytest

from modlink_core.replay.export_engine import ExportEngine, ExportJob, JobStatus
from modlink_core.replay.export_request import ExportMode, ExportRequest, StreamSelection

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(mode: ExportMode = ExportMode.SINGLE) -> ExportRequest:
    streams = (StreamSelection(stream_id="s1", format_id="signal_csv"),)
    if mode == ExportMode.MULTI:
        return ExportRequest(
            mode=mode,
            recording_ids=("rec1", "rec2"),
            streams=streams,
        )
    if mode == ExportMode.TIMESLICE:
        return ExportRequest(
            mode=mode,
            recording_ids=("rec1",),
            streams=streams,
            time_range_ns=(0, 1_000_000),
        )
    return ExportRequest(
        mode=mode,
        recording_ids=("rec1",),
        streams=streams,
    )


def _wait_for(
    engine: ExportEngine, job_id: str, target: JobStatus, timeout: float = 3.0
) -> ExportJob:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = engine.status(job_id)
        if job is not None and job.status == target:
            return job
        time.sleep(0.01)
    job = engine.status(job_id)
    raise TimeoutError(
        f"Job {job_id} did not reach {target} within {timeout}s; last status={job and job.status}"
    )


# ---------------------------------------------------------------------------
# Fixture: fresh engine with clean handler registry per test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_handlers():
    """Ensure _mode_handlers is empty before and after each test."""
    ExportEngine._mode_handlers.clear()
    yield
    ExportEngine._mode_handlers.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_enqueue_returns_job_id(tmp_path: Path) -> None:
    engine = ExportEngine()
    job_id = engine.enqueue(_make_request(), tmp_path)
    assert isinstance(job_id, str) and len(job_id) > 0


def test_job_starts_pending(tmp_path: Path) -> None:
    # Register a slow handler so the job stays RUNNING long enough to observe
    started = __import__("threading").Event()

    def slow_handler(req, root, progress_fn):
        started.set()
        time.sleep(10)  # will be interrupted by test teardown (daemon thread)
        return root / "out"

    ExportEngine.register_handler(ExportMode.SINGLE, slow_handler)

    engine = ExportEngine()
    job_id = engine.enqueue(_make_request(), tmp_path)

    # Status immediately after enqueue must be PENDING or RUNNING (never COMPLETED/FAILED yet)
    job = engine.status(job_id)
    assert job is not None
    assert job.status in (JobStatus.PENDING, JobStatus.RUNNING)


def test_job_completes(tmp_path: Path) -> None:
    expected_output = tmp_path / "result"

    def fast_handler(req, root, progress_fn):
        progress_fn("s1")
        return expected_output

    ExportEngine.register_handler(ExportMode.SINGLE, fast_handler)

    engine = ExportEngine()
    job_id = engine.enqueue(_make_request(), tmp_path)

    job = _wait_for(engine, job_id, JobStatus.COMPLETED)
    assert job.status == JobStatus.COMPLETED
    assert job.output_path == expected_output
    assert job.progress == 1.0
    assert job.error is None


def test_failed_job_has_error(tmp_path: Path) -> None:
    def failing_handler(req, root, progress_fn):
        raise RuntimeError("disk full")

    ExportEngine.register_handler(ExportMode.SINGLE, failing_handler)

    engine = ExportEngine()
    job_id = engine.enqueue(_make_request(), tmp_path)

    job = _wait_for(engine, job_id, JobStatus.FAILED)
    assert job.status == JobStatus.FAILED
    assert job.error == "disk full"


def test_cancel_pending_job(tmp_path: Path) -> None:
    """Enqueue 2 jobs; cancel second before first finishes; second must be CANCELLED."""
    first_started = __import__("threading").Event()
    first_release = __import__("threading").Event()

    def blocking_handler(req, root, progress_fn):
        first_started.set()
        first_release.wait(timeout=5.0)
        return root / "out"

    ExportEngine.register_handler(ExportMode.SINGLE, blocking_handler)

    engine = ExportEngine()
    engine.enqueue(_make_request(), tmp_path)
    job_id_2 = engine.enqueue(_make_request(), tmp_path)

    # Wait until first job is running so second is definitely still PENDING
    first_started.wait(timeout=3.0)

    engine.cancel(job_id_2)

    job2 = engine.status(job_id_2)
    assert job2 is not None
    assert job2.status == JobStatus.CANCELLED

    # Unblock first job so the engine thread can clean up
    first_release.set()


def test_progress_callback_fires(tmp_path: Path) -> None:
    received: list[tuple[str, float]] = []

    def handler(req, root, progress_fn):
        progress_fn("s1")
        return root / "out"

    ExportEngine.register_handler(ExportMode.SINGLE, handler)

    engine = ExportEngine(progress_callback=lambda jid, p: received.append((jid, p)))
    job_id = engine.enqueue(_make_request(), tmp_path)

    _wait_for(engine, job_id, JobStatus.COMPLETED)

    assert len(received) >= 1
    assert received[0][0] == job_id
    assert 0.0 < received[0][1] <= 1.0
