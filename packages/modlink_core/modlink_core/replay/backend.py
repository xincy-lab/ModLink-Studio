from __future__ import annotations

import bisect
import logging
import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path

from ..bus import StreamBus
from ..event_stream import BackendEventBroker
from ..models import (
    ExportJobSnapshot,
    ReplayMarker,
    ReplayRecordingSummary,
    ReplaySegment,
    ReplaySnapshot,
)
from ..settings import SettingsStore
from ..storage import (
    delete_recording,
    list_recordings,
    resolved_export_root_dir,
    resolved_storage_root_dir,
)
from .export import ExportService
from .export_request import ExportMode, ExportRequest, StreamSelection
from .reader import RecordingReader

ReplayCommand = tuple[Callable[[], None], Future[object]]
ReplayExportCommand = tuple[ExportRequest | str, str | Path | None]

logger = logging.getLogger(__name__)


class ReplayBackend:
    def __init__(
        self,
        *,
        settings: SettingsStore,
        parent: object | None = None,
    ) -> None:
        self._settings = settings
        self._parent = parent
        self.bus = StreamBus(event_broker=BackendEventBroker(), parent=self)
        self._export_service = ExportService()
        self._command_queue: queue.Queue[ReplayCommand | object] = queue.Queue()
        self._shutdown_sentinel = object()
        self._thread: threading.Thread | None = None
        self._state = "idle"
        self._started = False
        self._accepting_commands = False
        self._worker_exit_error: Exception | None = None
        self._lock = threading.RLock()
        self._recordings: tuple[ReplayRecordingSummary, ...] = ()
        self._reader: RecordingReader | None = None
        self._markers: tuple[ReplayMarker, ...] = ()
        self._segments: tuple[ReplaySegment, ...] = ()
        self._position_ns = 0
        self._speed_multiplier = 1.0
        self._timeline_index = 0
        self._play_started_wall_ns = 0
        self._play_started_position_ns = 0

    @property
    def is_started(self) -> bool:
        thread = self._thread
        return self._started and thread is not None and thread.is_alive()

    def start(self) -> None:
        if self.is_started:
            self._started = True
            self._accepting_commands = True
            return
        logger.info("Starting replay backend")
        self._export_service.start()
        thread = threading.Thread(
            target=self._run,
            name="modlink.replay",
            daemon=True,
        )
        self._thread = thread
        self._worker_exit_error = None
        self._accepting_commands = True
        self._started = True
        thread.start()
        self.refresh_recordings()

    def shutdown(self, *, timeout_ms: int = 3000) -> None:
        logger.info("Shutting down replay backend")
        with self._lock:
            self._accepting_commands = False
            thread = self._thread
            worker_exit_error = self._worker_exit_error

        if thread is None or not thread.is_alive():
            self._finalize_shutdown()
            self._export_service.shutdown(timeout_ms=timeout_ms)
            if worker_exit_error is not None:
                self._worker_exit_error = None
                raise worker_exit_error
            return

        self._command_queue.put(self._shutdown_sentinel)
        thread.join(max(0, timeout_ms) / 1000)
        if thread.is_alive():
            raise TimeoutError(f"replay shutdown timed out after {timeout_ms}ms")

        self._finalize_shutdown()
        self._export_service.shutdown(timeout_ms=timeout_ms)
        worker_exit_error = self._take_worker_exit_error()
        if worker_exit_error is not None:
            raise worker_exit_error

    def snapshot(self) -> ReplaySnapshot:
        reader = self._reader
        return ReplaySnapshot(
            state=self._state,
            is_started=self.is_started,
            recording_id=None if reader is None else reader.recording_id,
            recording_path=None if reader is None else str(reader.recording_path),
            position_ns=int(self._position_ns),
            duration_ns=0 if reader is None else int(reader.duration_ns),
            speed_multiplier=float(self._speed_multiplier),
        )

    def recordings(self) -> tuple[ReplayRecordingSummary, ...]:
        return self._recordings

    def markers(self) -> tuple[ReplayMarker, ...]:
        return self._markers

    def segments(self) -> tuple[ReplaySegment, ...]:
        return self._segments

    def export_jobs(self) -> tuple[ExportJobSnapshot, ...]:
        return self._export_service.jobs()

    def refresh_recordings(self) -> Future[tuple[ReplayRecordingSummary, ...]]:
        return self._submit_command(self._refresh_recordings_worker)

    def open_recording(self, recording_path: str | Path) -> Future[ReplaySnapshot]:
        return self._submit_command(self._open_recording_worker, recording_path)

    def play(self) -> Future[None]:
        return self._submit_command(self._play_worker)

    def pause(self) -> Future[None]:
        return self._submit_command(self._pause_worker)

    def stop(self) -> Future[None]:
        return self._submit_command(self._stop_worker)

    def seek(self, position_ns: int) -> Future[None]:
        return self._submit_command(self._seek_worker, position_ns)

    def set_speed(self, multiplier: float) -> Future[float]:
        return self._submit_command(self._set_speed_worker, multiplier)

    def start_export(
        self,
        request: ExportRequest | str,
        output_root_dir: str | Path | None = None,
    ) -> Future[ExportJobSnapshot]:
        return self._submit_command(self._start_export_worker, (request, output_root_dir))

    def delete_recording(self, recording_id: str) -> Future[tuple[ReplayRecordingSummary, ...]]:
        return self._submit_command(self._delete_recording_worker, recording_id)

    def _run(self) -> None:
        exit_error: Exception | None = None
        while True:
            try:
                if self._drain_commands():
                    return
                if self._state != "playing":
                    time.sleep(0.01)
                    continue
                self._tick_playback()
            except Exception as exc:
                logger.exception("Replay worker exited with an unexpected error")
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
                return True

            command, _future = item
            command()

    def _refresh_recordings_worker(self) -> tuple[ReplayRecordingSummary, ...]:
        root_dir = resolved_storage_root_dir(self._settings)
        summaries: list[ReplayRecordingSummary] = []
        for manifest in list_recordings(root_dir):
            recording_id = manifest.get("recording_id")
            if not isinstance(recording_id, str) or recording_id == "":
                continue
            stream_ids_payload = manifest.get("stream_ids", [])
            stream_ids = tuple(
                stream_id for stream_id in stream_ids_payload if isinstance(stream_id, str)
            )
            label = manifest.get("recording_label")
            session_name = manifest.get("session_name")
            experiment_name = manifest.get("experiment_name")
            started_at_ns = manifest.get("started_at_ns")
            duration_ns_raw = manifest.get("duration_ns")
            status = manifest.get("status")
            frame_counts = manifest.get("frame_counts_by_stream")
            total_frames = sum(frame_counts.values()) if isinstance(frame_counts, dict) else None
            summaries.append(
                ReplayRecordingSummary(
                    recording_id=recording_id,
                    recording_label=label
                    if isinstance(label, str) or label is None
                    else str(label),
                    recording_path=str(root_dir / "recordings" / recording_id),
                    stream_ids=stream_ids,
                    session_name=session_name if isinstance(session_name, str) else None,
                    experiment_name=experiment_name if isinstance(experiment_name, str) else None,
                    started_at_ns=started_at_ns if isinstance(started_at_ns, int) else None,
                    duration_ns=duration_ns_raw if isinstance(duration_ns_raw, int) else None,
                    status=status if isinstance(status, str) else None,
                    total_frames=total_frames,
                )
            )
        self._recordings = tuple(summaries)
        return self._recordings

    def _open_recording_worker(self, recording_path: str | Path) -> ReplaySnapshot:
        logger.info("Opening replay recording from %s", recording_path)
        reader = RecordingReader(recording_path)
        self._reader = reader
        self._markers = reader.markers()
        self._segments = reader.segments()
        self._position_ns = 0
        self._speed_multiplier = 1.0
        self._timeline_index = 0
        self._play_started_wall_ns = 0
        self._play_started_position_ns = 0
        self._rebuild_bus(reader)
        self._set_state("ready")
        logger.debug(
            "Replay recording opened: recording_id=%s duration_ns=%s stream_count=%s",
            reader.recording_id,
            reader.duration_ns,
            len(reader.descriptors()),
        )
        return self.snapshot()

    def _play_worker(self) -> None:
        reader = self._require_reader()
        if not reader.frames():
            raise RuntimeError("REPLAY_EMPTY_RECORDING")
        if self._state == "playing":
            return
        if self._state == "finished":
            self._position_ns = 0
            self._timeline_index = 0
        self._play_started_wall_ns = time.monotonic_ns()
        self._play_started_position_ns = self._position_ns
        self._set_state("playing")

    def _pause_worker(self) -> None:
        if self._state != "playing":
            raise RuntimeError("REPLAY_NOT_PLAYING")
        self._sync_playback_position(time.monotonic_ns())
        self._set_state("paused")

    def _stop_worker(self) -> None:
        self._require_reader()
        self._position_ns = 0
        self._timeline_index = 0
        self._play_started_wall_ns = 0
        self._play_started_position_ns = 0
        self._set_state("ready")

    def _set_speed_worker(self, multiplier: object) -> float:
        try:
            resolved = float(multiplier)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("REPLAY_INVALID_SPEED") from exc
        if resolved not in {1.0, 2.0, 4.0}:
            raise RuntimeError("REPLAY_INVALID_SPEED")
        if self._state == "playing":
            current_time_ns = time.monotonic_ns()
            self._sync_playback_position(current_time_ns)
            self._play_started_wall_ns = current_time_ns
            self._play_started_position_ns = self._position_ns
        self._speed_multiplier = resolved
        return self._speed_multiplier

    def _seek_worker(self, position_ns: object) -> None:
        reader = self._require_reader()
        try:
            target_ns = int(position_ns)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("REPLAY_INVALID_SEEK_POSITION") from exc
        target_ns = max(0, min(target_ns, reader.duration_ns))

        # Use bisect to find the correct timeline index for the target position.
        timeline = reader.frames()
        timestamps = [ref.relative_timestamp_ns for ref in timeline]
        self._timeline_index = bisect.bisect_right(timestamps, target_ns)
        self._position_ns = target_ns

        if self._state == "playing":
            # Reset wall-clock anchor so playback continues from the new position.
            self._play_started_wall_ns = time.monotonic_ns()
            self._play_started_position_ns = target_ns
        elif self._state == "finished":
            self._set_state("paused")

    def _start_export_worker(self, request: object) -> ExportJobSnapshot:
        if not isinstance(request, tuple) or len(request) != 2:
            raise RuntimeError("REPLAY_EXPORT_FORMAT_UNSUPPORTED")
        raw_request, output_root_dir = request
        if isinstance(raw_request, ExportRequest):
            export_request = raw_request
        elif isinstance(raw_request, str) and raw_request.strip():
            reader = self._require_reader()
            format_id = raw_request.strip()
            required_payload = format_id.split("_")[0]
            selections = tuple(
                StreamSelection(stream_id=stream_id, format_id=format_id)
                for stream_id, descriptor in reader.descriptors().items()
                if descriptor.payload_type == required_payload
            )
            if not selections:
                return self._export_service.enqueue_failed(
                    recording_id=reader.recording_id,
                    request_summary=format_id,
                    error=f"no {required_payload!r} streams in recording",
                )
            export_request = ExportRequest(
                mode=ExportMode.SINGLE,
                recording_ids=(reader.recording_id,),
                streams=selections,
            )
        else:
            raise RuntimeError("REPLAY_EXPORT_FORMAT_UNSUPPORTED")
        export_root_dir = (
            Path(output_root_dir)
            if isinstance(output_root_dir, str | Path) and str(output_root_dir).strip()
            else resolved_export_root_dir(self._settings)
        )
        storage_root_dir = resolved_storage_root_dir(self._settings)
        return self._export_service.enqueue(export_request, export_root_dir, storage_root_dir)

    def _delete_recording_worker(self, recording_id: object) -> tuple[ReplayRecordingSummary, ...]:
        if not isinstance(recording_id, str) or not recording_id.strip():
            raise RuntimeError("REPLAY_DELETE_INVALID_ID")

        # If the recording is currently open for replay, drop the reader and
        # clear the bus so the deletion can't race with playback frame loads.
        reader = self._reader
        if reader is not None and reader.recording_id == recording_id:
            self._reader = None
            self._markers = ()
            self._segments = ()
            self._position_ns = 0
            self._timeline_index = 0
            self._play_started_wall_ns = 0
            self._play_started_position_ns = 0
            for stream_id in tuple(self.bus.descriptors()):
                self.bus.remove_descriptor(stream_id)
            self._set_state("idle")

        root_dir = resolved_storage_root_dir(self._settings)
        try:
            delete_recording(root_dir, recording_id)
        except FileNotFoundError as exc:
            raise RuntimeError(f"REPLAY_DELETE_NOT_FOUND: {recording_id}") from exc
        logger.info("Deleted replay recording %s", recording_id)
        return self._refresh_recordings_worker()

    def _tick_playback(self) -> None:
        current_time_ns = time.monotonic_ns()
        target_position_ns = self._sync_playback_position(current_time_ns)
        reader = self._reader
        if reader is None:
            return
        if (
            self._timeline_index >= len(reader.frames())
            and target_position_ns >= reader.duration_ns
        ):
            self._position_ns = reader.duration_ns
            self._set_state("finished")
            return
        time.sleep(0.005)

    def _sync_playback_position(self, current_time_ns: int) -> int:
        reader = self._reader
        if reader is None:
            return self._position_ns
        target_position_ns = min(
            reader.duration_ns,
            int(
                self._play_started_position_ns
                + (current_time_ns - self._play_started_wall_ns) * self._speed_multiplier
            ),
        )
        self._emit_due_frames(target_position_ns)
        self._position_ns = target_position_ns
        return target_position_ns

    def _emit_due_frames(self, target_position_ns: int) -> None:
        reader = self._reader
        if reader is None:
            return
        timeline = reader.frames()
        while self._timeline_index < len(timeline):
            ref = timeline[self._timeline_index]
            if ref.relative_timestamp_ns > target_position_ns:
                break
            self.bus.ingest_frame(reader.load_frame(ref))
            self._timeline_index += 1

    def _rebuild_bus(self, reader: RecordingReader) -> None:
        for stream_id in tuple(self.bus.descriptors()):
            self.bus.remove_descriptor(stream_id)
        self.bus.add_descriptors(reader.descriptors().values())

    def _set_state(self, state: str) -> None:
        with self._lock:
            if self._state == state:
                return
            self._state = state

    def _require_reader(self) -> RecordingReader:
        if self._reader is None:
            raise RuntimeError("REPLAY_NOT_OPEN")
        return self._reader

    def _submit_command(
        self,
        worker_method: Callable[..., object],
        *args: object,
    ) -> Future[object]:
        future: Future[object] = Future()
        if not self.is_started:
            future.set_exception(RuntimeError("REPLAY_NOT_STARTED"))
            return future
        if not self._accepting_commands:
            future.set_exception(RuntimeError("REPLAY_SHUTTING_DOWN"))
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

    def _finalize_shutdown(self) -> None:
        self._set_state("idle")
        self._started = False
        self._accepting_commands = True
        self._thread = None

    def _take_worker_exit_error(self) -> Exception | None:
        with self._lock:
            error = self._worker_exit_error
            self._worker_exit_error = None
            return error
