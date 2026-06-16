from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .export_request import ExportMode, ExportRequest


class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ExportJob:
    job_id: str
    request: ExportRequest
    output_root: Path
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0  # 0.0 to 1.0
    error: str | None = None
    output_path: Path | None = None  # set on completion


ExportProgressCallback = Callable[[str, float], None]  # (job_id, progress 0-1)


class ExportEngine:
    """Serial export queue. One job runs at a time. Thread-safe enqueue/cancel."""

    # Mode handler registry — set by ExportEngine users or tests
    _mode_handlers: dict = {}

    def __init__(self, progress_callback: ExportProgressCallback | None = None) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, ExportJob] = {}
        self._queue: list[str] = []  # job_ids in FIFO order
        self._running: str | None = None
        self._cancel_requested: set[str] = set()
        self._progress_callback = progress_callback
        # _work_event must be created before the worker thread starts
        self._work_event = threading.Event()
        self._worker = threading.Thread(target=self._run_loop, daemon=True)
        self._worker.start()

    def enqueue(self, request: ExportRequest, output_root: Path) -> str:
        """Add a job to the queue. Returns job_id."""
        job_id = uuid.uuid4().hex
        job = ExportJob(job_id=job_id, request=request, output_root=output_root)
        with self._lock:
            self._jobs[job_id] = job
            self._queue.append(job_id)
        self._work_event.set()
        return job_id

    def status(self, job_id: str) -> ExportJob | None:
        """Return current job state, or None if unknown."""
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> None:
        """Cancel a pending or running job."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if job.status == JobStatus.PENDING:
                job.status = JobStatus.CANCELLED
                self._queue.remove(job_id)
            elif job.status == JobStatus.RUNNING:
                self._cancel_requested.add(job_id)

    def _run_loop(self) -> None:
        while True:
            self._work_event.wait()
            self._work_event.clear()
            while True:
                with self._lock:
                    if not self._queue:
                        break
                    job_id = self._queue.pop(0)
                    job = self._jobs[job_id]
                    job.status = JobStatus.RUNNING
                    self._running = job_id
                self._execute(job)
                with self._lock:
                    self._running = None

    def _execute(self, job: ExportJob) -> None:
        """Execute one job. Calls mode-specific handler. Updates job status."""
        try:
            handler = self._mode_handlers.get(job.request.mode)
            if handler is None:
                raise NotImplementedError(f"No handler for mode {job.request.mode}")

            def progress_fn(stream_id: str) -> None:
                # Called once per completed stream
                with self._lock:
                    job.progress = min(1.0, job.progress + 1.0 / max(1, len(job.request.streams)))
                if self._progress_callback:
                    self._progress_callback(job.job_id, job.progress)
                if job.job_id in self._cancel_requested:
                    raise InterruptedError("Export cancelled")

            output_path = handler(job.request, job.output_root, progress_fn)
            with self._lock:
                job.status = JobStatus.COMPLETED
                job.progress = 1.0
                job.output_path = output_path
                self._cancel_requested.discard(job.job_id)
        except InterruptedError:
            with self._lock:
                job.status = JobStatus.CANCELLED
                self._cancel_requested.discard(job.job_id)
        except Exception as e:
            with self._lock:
                job.status = JobStatus.FAILED
                job.error = str(e)
                self._cancel_requested.discard(job.job_id)

    @classmethod
    def register_handler(cls, mode: ExportMode, handler: Callable) -> None:
        cls._mode_handlers[mode] = handler
