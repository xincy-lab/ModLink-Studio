from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path

from modlink_sdk import FrameEnvelope, StreamDescriptor

from ..bus import FrameStream, FrameStreamOverflowError, StreamBus
from ..event_stream import StreamClosedError
from ..events import (
    BackendEvent,
    RecordingFailedEvent,
)
from ..models import RecordingSnapshot, RecordingStartSummary, RecordingStopSummary
from ..settings import SettingsStore
from ..storage import (
    add_recording_marker,
    add_recording_segment,
    append_recording_frame,
    create_recording,
    finalize_recording,
    resolved_storage_root_dir,
)

RECORDING_CONSUMER_NAME = "recording"
RecordingCommand = tuple[Callable[[], None], Future[object]]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ActiveRecording:
    root_dir: str
    recording_id: str
    recording_path: str
    started_at_ns: int
    frame_counts_by_stream: dict[str, int]


class RecordingBackend:
    """Threaded recording backend that persists bus frames to disk."""

    def __init__(
        self,
        bus: StreamBus,
        *,
        settings: SettingsStore,
        publish_event: Callable[[BackendEvent], None],
        parent: object | None = None,
    ) -> None:
        self._bus = bus
        self._settings = settings
        self._publish_event = publish_event
        self._parent = parent
        self._command_queue: queue.Queue[RecordingCommand | object] = queue.Queue()
        self._shutdown_sentinel = object()
        self._thread: threading.Thread | None = None
        self._frame_stream: FrameStream | None = None
        self._state = "idle"
        self._started = False
        self._accepting_commands = False
        self._worker_exit_error: Exception | None = None
        self._active_recording: ActiveRecording | None = None
        self._lock = threading.RLock()

    @property
    def root_dir(self) -> Path:
        return resolved_storage_root_dir(self._settings)

    @property
    def is_started(self) -> bool:
        thread = self._thread
        return self._started and thread is not None and thread.is_alive()

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_recording(self) -> bool:
        return self._state == "recording"

    def snapshot(self) -> RecordingSnapshot:
        return RecordingSnapshot(
            state=self._state,
            is_started=self.is_started,
            is_recording=self.is_recording,
            root_dir=str(self.root_dir),
        )

    def start(self) -> None:
        if self.is_started:
            self._started = True
            self._accepting_commands = True
            return
        logger.info("Starting recording backend")
        if self._frame_stream is None or self._frame_stream.closed:
            self._frame_stream = self._open_frame_stream()
        thread = threading.Thread(
            target=self._run,
            name="modlink.recording",
            daemon=True,
        )
        self._thread = thread
        self._worker_exit_error = None
        self._accepting_commands = True
        self._started = True
        thread.start()
        logger.info("Recording backend started")

    def start_recording(
        self,
        recording_label: str | None = None,
        *,
        session_name: str | None = None,
        experiment_name: str | None = None,
    ) -> Future[RecordingStartSummary]:
        storage_root_dir = self.root_dir
        recordings_root_dir = storage_root_dir / "recordings"
        return self._submit_command(
            self._start_recording_worker,
            str(storage_root_dir),
            str(recordings_root_dir),
            recording_label,
            session_name,
            experiment_name,
            self._bus.descriptors(),
        )

    def stop_recording(self) -> Future[RecordingStopSummary]:
        return self._submit_command(self._stop_recording_worker)

    def add_marker(self, label: str | None = None) -> Future[None]:
        return self._submit_command(self._add_marker_worker, label)

    def add_segment(
        self,
        start_ns: int,
        end_ns: int,
        label: str | None = None,
    ) -> Future[None]:
        return self._submit_command(
            self._add_segment_worker,
            start_ns,
            end_ns,
            label,
        )

    def shutdown(self, *, timeout_ms: int = 3000) -> None:
        logger.info("Shutting down recording backend")
        with self._lock:
            self._accepting_commands = False
            thread = self._thread
            worker_exit_error = self._worker_exit_error

        if thread is None or not thread.is_alive():
            self._finalize_shutdown()
            if worker_exit_error is not None:
                self._worker_exit_error = None
                raise worker_exit_error
            return

        self._command_queue.put(self._shutdown_sentinel)
        thread.join(max(0, timeout_ms) / 1000)

        if thread.is_alive():
            raise TimeoutError(f"recording shutdown timed out after {timeout_ms}ms")

        self._finalize_shutdown()
        worker_exit_error = self._take_worker_exit_error()
        if worker_exit_error is not None:
            raise worker_exit_error
        logger.info("Recording backend shut down")

    def _run(self) -> None:
        exit_error: Exception | None = None
        while True:
            try:
                if self._drain_commands():
                    return

                frame_stream = self._frame_stream
                if frame_stream is None:
                    time.sleep(0.01)
                    continue

                try:
                    frame = frame_stream.read(timeout=0.05)
                except queue.Empty:
                    continue
                except StreamClosedError:
                    if not self._started:
                        return
                    logger.warning("Recording frame stream closed unexpectedly; reopening stream")
                    self._frame_stream = self._open_frame_stream()
                    continue
                except FrameStreamOverflowError as exc:
                    self._handle_frame_stream_overflow(exc.consumer_name)
                    continue

                if not self.is_recording:
                    continue
                self._on_frame_worker(frame)
            except Exception as exc:
                logger.exception("Recording worker exited with an unexpected error")
                exit_error = exc
                break

        with self._lock:
            self._worker_exit_error = exit_error
            self._started = False
            self._accepting_commands = False

    def _drain_commands(self) -> bool:
        while True:
            try:
                item = self._command_queue.get_nowait()
            except queue.Empty:
                return False

            if item is self._shutdown_sentinel:
                try:
                    self._shutdown_worker()
                finally:
                    self._fail_pending_commands("ACQ_SHUTDOWN")
                return True

            command, _future = item
            command()

    def _on_frame_worker(self, frame: object) -> None:
        if not isinstance(frame, FrameEnvelope):
            return
        if self._active_recording is None:
            return

        stream_id = frame.stream_id
        next_index = self._active_recording.frame_counts_by_stream[stream_id] + 1
        try:
            append_recording_frame(
                Path(self._active_recording.root_dir),
                self._active_recording.recording_id,
                frame,
                frame_index=next_index,
            )
            self._active_recording.frame_counts_by_stream[stream_id] = next_index
        except Exception:
            logger.exception("Recording append failed; marking recording as failed")
            self._fail_recording_worker("write_failed")

    def _start_recording_worker(
        self,
        root_dir: str,
        recordings_dir: str,
        recording_label: object,
        session_name: object,
        experiment_name: object,
        recording_descriptors: object,
    ) -> RecordingStartSummary:
        if self._active_recording is not None:
            raise RuntimeError("ACQ_ALREADY_RECORDING")

        if not isinstance(recording_descriptors, dict) or not all(
            isinstance(value, StreamDescriptor) for value in recording_descriptors.values()
        ):
            raise RuntimeError("ACQ_INVALID_DESCRIPTOR_SNAPSHOT")

        started_at_ns = time.time_ns()
        try:
            recording_id = create_recording(
                Path(root_dir),
                recording_descriptors,
                recording_label=recording_label or None,
                session_name=session_name if isinstance(session_name, str) else None,
                experiment_name=experiment_name if isinstance(experiment_name, str) else None,
            )
        except Exception as exc:
            self._active_recording = None
            raise RuntimeError(f"ACQ_START_FAILED: {type(exc).__name__}: {exc}") from exc

        recording_path = str(Path(recordings_dir) / recording_id)
        self._active_recording = ActiveRecording(
            root_dir=root_dir,
            recording_id=recording_id,
            recording_path=recording_path,
            started_at_ns=started_at_ns,
            frame_counts_by_stream={stream_id: 0 for stream_id in recording_descriptors},
        )
        self._set_state("recording")
        logger.info("Started recording %s at %s", recording_id, recording_path)
        return RecordingStartSummary(
            recording_id=recording_id,
            recording_path=recording_path,
            started_at_ns=started_at_ns,
        )

    def _stop_recording_worker(self) -> RecordingStopSummary:
        return self._stop_recording_worker_with_policy(publish_failure=True)

    def _stop_recording_worker_with_policy(
        self,
        *,
        publish_failure: bool,
    ) -> RecordingStopSummary:
        if self._active_recording is None:
            raise RuntimeError("ACQ_STOP_IGNORED: not recording")

        _ = publish_failure
        stopped_at_ns = time.time_ns()
        active_recording = self._active_recording
        self._active_recording = None
        self._set_state("idle")
        logger.info("Stopped recording %s", active_recording.recording_id)
        summary = RecordingStopSummary(
            recording_id=active_recording.recording_id,
            recording_path=active_recording.recording_path,
            started_at_ns=active_recording.started_at_ns,
            stopped_at_ns=stopped_at_ns,
            status="completed",
            frame_counts_by_stream=dict(active_recording.frame_counts_by_stream),
        )
        try:
            finalize_recording(
                Path(active_recording.root_dir),
                active_recording.recording_id,
                started_at_ns=active_recording.started_at_ns,
                stopped_at_ns=stopped_at_ns,
                status="completed",
                frame_counts_by_stream=dict(active_recording.frame_counts_by_stream),
            )
        except Exception as exc:
            logger.warning(
                "Failed to finalize recording manifest %s: %s", active_recording.recording_id, exc
            )
        return summary

    def _add_marker_worker(self, label: object) -> None:
        if self._active_recording is None:
            raise RuntimeError("ACQ_MARKER_REJECTED: not recording")

        timestamp_ns = time.time_ns()
        normalized_label = label or None
        try:
            add_recording_marker(
                Path(self._active_recording.root_dir),
                self._active_recording.recording_id,
                timestamp_ns=timestamp_ns,
                label=normalized_label,
            )
        except Exception as exc:
            raise RuntimeError(f"ACQ_MARKER_FAILED: {type(exc).__name__}: {exc}") from exc

    def _add_segment_worker(
        self,
        start_ns: object,
        end_ns: object,
        label: object,
    ) -> None:
        if self._active_recording is None:
            raise RuntimeError("ACQ_SEGMENT_REJECTED: not recording")

        try:
            start_value = int(start_ns)
            end_value = int(end_ns)
        except (TypeError, ValueError):
            raise RuntimeError("ACQ_INVALID_SEGMENT_RANGE")

        if start_value > end_value:
            raise RuntimeError("ACQ_INVALID_SEGMENT_RANGE: start_ns > end_ns")

        normalized_label = label or None
        try:
            add_recording_segment(
                Path(self._active_recording.root_dir),
                self._active_recording.recording_id,
                start_ns=start_value,
                end_ns=end_value,
                label=normalized_label,
            )
        except Exception as exc:
            raise RuntimeError(f"ACQ_SEGMENT_FAILED: {type(exc).__name__}: {exc}") from exc

    def _handle_frame_stream_overflow(self, consumer_name: str) -> None:
        logger.warning("Recording frame stream overflowed for consumer '%s'", consumer_name)
        if self._active_recording is not None:
            self._fail_recording_worker("frame_stream_overflow")
        self._replace_frame_stream()

    def _replace_frame_stream(self) -> None:
        previous_stream = self._frame_stream
        self._frame_stream = self._open_frame_stream()
        if previous_stream is not None:
            previous_stream.close()

    def _open_frame_stream(self) -> FrameStream:
        return self._bus.open_frame_stream(
            maxsize=256,
            drop_policy="error",
            consumer_name=RECORDING_CONSUMER_NAME,
        )

    def _shutdown_worker(self) -> None:
        if self._active_recording is not None:
            self._stop_recording_worker_with_policy(publish_failure=False)

    def _fail_recording_worker(self, reason: str) -> None:
        active_recording = self._active_recording
        if active_recording is None:
            return

        stopped_at_ns = time.time_ns()
        self._active_recording = None
        self._set_state("idle")
        try:
            finalize_recording(
                Path(active_recording.root_dir),
                active_recording.recording_id,
                started_at_ns=active_recording.started_at_ns,
                stopped_at_ns=stopped_at_ns,
                status="failed",
                frame_counts_by_stream=dict(active_recording.frame_counts_by_stream),
            )
        except Exception as exc:
            logger.warning(
                "Failed to finalize failed recording manifest %s: %s",
                active_recording.recording_id,
                exc,
            )
        self._publish_recording_failed(
            active_recording,
            stopped_at_ns=stopped_at_ns,
            reason=reason,
        )

    def _publish_recording_failed(
        self,
        active_recording: ActiveRecording,
        *,
        stopped_at_ns: int,
        reason: str,
    ) -> None:
        self._publish_event(
            RecordingFailedEvent(
                recording_id=active_recording.recording_id,
                recording_path=active_recording.recording_path,
                frame_counts_by_stream=dict(active_recording.frame_counts_by_stream),
                reason=reason,
                ts_ns=stopped_at_ns,
            )
        )

    def _set_state(self, state: str) -> None:
        with self._lock:
            if state == self._state:
                return
            self._state = state

    def _submit_command(
        self,
        worker_method: Callable[..., object],
        *args: object,
    ) -> Future[object]:
        future: Future[object] = Future()
        if not self.is_started:
            future.set_exception(RuntimeError("ACQ_NOT_STARTED"))
            return future
        if not self._accepting_commands:
            future.set_exception(RuntimeError("ACQ_SHUTTING_DOWN"))
            return future

        def _run_command() -> None:
            try:
                result = worker_method(*args)
            except Exception as exc:
                if not future.done():
                    future.set_exception(exc)
                return
            if not future.done():
                future.set_result(result)

        self._command_queue.put((_run_command, future))
        return future

    def _fail_pending_commands(self, message: str) -> None:
        while True:
            try:
                item = self._command_queue.get_nowait()
            except queue.Empty:
                return
            if item is self._shutdown_sentinel:
                continue
            _command, future = item
            if future is None or future.done():
                continue
            future.set_exception(RuntimeError(message))

    def _finalize_shutdown(self) -> None:
        self._set_state("idle")
        self._started = False
        self._accepting_commands = True
        self._thread = None
        if self._frame_stream is not None:
            self._frame_stream.close()
            self._frame_stream = None

    def _take_worker_exit_error(self) -> Exception | None:
        with self._lock:
            error = self._worker_exit_error
            self._worker_exit_error = None
            return error
