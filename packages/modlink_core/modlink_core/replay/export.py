from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ..models import ExportJobSnapshot
from .export_modes.cross import export_cross_recording_stream
from .export_modes.multi import export_multi_recording
from .export_modes.single import export_single_recording
from .export_modes.time_slice import export_time_slice
from .export_request import ExportMode, ExportRequest
from .store import RecordingStore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _ExportRequest:
    job_id: str
    request: ExportRequest
    request_summary: str
    output_root_dir: Path
    storage_root_dir: Path


class ExportService:
    def __init__(self) -> None:
        self._jobs: dict[str, ExportJobSnapshot] = {}
        self._job_order: list[str] = []
        self._lock = threading.RLock()
        self._queue: queue.Queue[_ExportRequest | object] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._shutdown_sentinel = object()
        self._shutdown_requested = threading.Event()
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._shutdown_requested.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="modlink.replay.export",
            daemon=True,
        )
        self._started = True
        self._thread.start()

    def shutdown(self, *, timeout_ms: int = 3000) -> None:
        if not self._started:
            return
        self._shutdown_requested.set()
        self._cancel_pending_jobs()
        self._queue.put(self._shutdown_sentinel)
        thread = self._thread
        if thread is not None:
            thread.join(max(0, timeout_ms) / 1000)
            if thread.is_alive():
                logger.warning("Replay export shutdown is still waiting on an active export")
                return
        self._thread = None
        self._started = False

    def jobs(self) -> tuple[ExportJobSnapshot, ...]:
        with self._lock:
            return tuple(self._jobs[job_id] for job_id in self._job_order)

    def enqueue(
        self,
        request: ExportRequest,
        output_root_dir: Path,
        storage_root_dir: Path,
    ) -> ExportJobSnapshot:
        job_id = uuid4().hex
        request_summary = _summarize_request(request)
        snapshot = ExportJobSnapshot(
            job_id=job_id,
            recording_id=request.recording_ids[0],
            state="queued",
            progress=0.0,
            output_path=None,
            error=None,
            request_summary=request_summary,
        )
        with self._lock:
            self._jobs[job_id] = snapshot
            self._job_order.append(job_id)
        self._queue.put(
            _ExportRequest(
                job_id=job_id,
                request=request,
                request_summary=request_summary,
                output_root_dir=Path(output_root_dir),
                storage_root_dir=Path(storage_root_dir),
            )
        )
        return snapshot

    def enqueue_failed(
        self,
        *,
        recording_id: str,
        request_summary: str,
        error: str,
    ) -> ExportJobSnapshot:
        job_id = uuid4().hex
        snapshot = ExportJobSnapshot(
            job_id=job_id,
            recording_id=recording_id,
            state="failed",
            progress=1.0,
            output_path=None,
            error=error,
            request_summary=request_summary,
        )
        with self._lock:
            self._jobs[job_id] = snapshot
            self._job_order.append(job_id)
        return snapshot

    def _run(self) -> None:
        try:
            while True:
                item = self._queue.get()
                if item is self._shutdown_sentinel:
                    return
                if not isinstance(item, _ExportRequest):
                    continue
                if self._shutdown_requested.is_set():
                    self._cancel_job(item.job_id)
                    continue
                self._process_request(item)
        finally:
            self._thread = None
            self._started = False

    def _process_request(self, request: _ExportRequest) -> None:
        self._update_job(
            request.job_id,
            state="running",
            progress=0.0,
            output_path=None,
            error=None,
        )

        try:
            output_path = self._run_export(request)
        except InterruptedError:
            self._cancel_job(request.job_id)
            return
        except Exception as exc:
            self._update_job(
                request.job_id,
                state="failed",
                progress=1.0,
                output_path=None,
                error=f"{type(exc).__name__}: {exc}",
            )
            return

        self._update_job(
            request.job_id,
            state="completed",
            progress=1.0,
            output_path=str(output_path),
            error=None,
        )

    def _run_export(self, request: _ExportRequest) -> Path:
        store = RecordingStore(request.storage_root_dir)
        export_request = request.request

        def progress_fn(_stream_id: str) -> None:
            self._raise_if_shutdown_requested()
            self._update_progress(request.job_id, 0.5)
            self._raise_if_shutdown_requested()

        if export_request.mode == ExportMode.SINGLE:
            reader = store.open(export_request.recording_ids[0])
            return export_single_recording(
                export_request,
                reader,
                request.output_root_dir,
                progress_fn,
            )
        if export_request.mode == ExportMode.TIMESLICE:
            reader = store.open(export_request.recording_ids[0])
            return export_time_slice(
                export_request,
                reader,
                request.output_root_dir,
                progress_fn,
            )
        if export_request.mode == ExportMode.MULTI:
            return export_multi_recording(
                export_request,
                store,
                request.output_root_dir,
                progress_fn,
            )
        if export_request.mode == ExportMode.CROSS_STREAM:
            return export_cross_recording_stream(
                export_request,
                store,
                request.output_root_dir,
                progress_fn,
            )
        raise ValueError(f"unknown export mode {export_request.mode!r}")

    def _raise_if_shutdown_requested(self) -> None:
        if self._shutdown_requested.is_set():
            raise InterruptedError("Export cancelled during shutdown")

    def _cancel_pending_jobs(self) -> None:
        pending_items: list[_ExportRequest] = []
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is self._shutdown_sentinel:
                continue
            if isinstance(item, _ExportRequest):
                pending_items.append(item)
        for item in pending_items:
            self._cancel_job(item.job_id)

    def _cancel_job(self, job_id: str) -> None:
        self._update_job(
            job_id,
            state="cancelled",
            progress=1.0,
            output_path=None,
            error=None,
        )

    def _update_progress(self, job_id: str, value: float) -> None:
        with self._lock:
            snapshot = self._jobs[job_id]
            self._jobs[job_id] = ExportJobSnapshot(
                job_id=snapshot.job_id,
                recording_id=snapshot.recording_id,
                state=snapshot.state,
                progress=min(1.0, max(0.0, float(value))),
                output_path=snapshot.output_path,
                error=snapshot.error,
                request_summary=snapshot.request_summary,
            )

    def _update_job(
        self,
        job_id: str,
        *,
        state: str,
        progress: float,
        output_path: str | None,
        error: str | None,
    ) -> None:
        with self._lock:
            snapshot = self._jobs[job_id]
            self._jobs[job_id] = ExportJobSnapshot(
                job_id=snapshot.job_id,
                recording_id=snapshot.recording_id,
                state=state,
                progress=min(1.0, max(0.0, float(progress))),
                output_path=output_path,
                error=error,
                request_summary=snapshot.request_summary,
            )


def _summarize_request(request: ExportRequest) -> str:
    streams = ", ".join(f"{item.stream_id}:{item.format_id}" for item in request.streams)
    recordings = ", ".join(request.recording_ids)
    return f"{request.mode.value} | {recordings} | {streams}"
