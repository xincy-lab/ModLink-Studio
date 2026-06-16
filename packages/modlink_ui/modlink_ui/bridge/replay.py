from __future__ import annotations

import logging
from concurrent.futures import CancelledError, Future
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal, pyqtSlot

from modlink_core.models import (
    ExportJobSnapshot,
    ReplayMarker,
    ReplayRecordingSummary,
    ReplaySegment,
    ReplaySnapshot,
)
from modlink_core.replay.backend import ReplayBackend
from modlink_core.replay.export_request import ExportRequest
from modlink_core.settings import (
    STORAGE_ROOT_DIR_KEY,
    resolved_export_root_dir,
    resolved_storage_root_dir,
)

from .bus import QtBusBridge
from .frame_pump import LatestFramePump
from .settings import QtSettingsBridge

logger = logging.getLogger(__name__)


class QtReplayBridge(QObject):
    sig_snapshot_changed = pyqtSignal(object)
    sig_recordings_changed = pyqtSignal()
    sig_annotations_changed = pyqtSignal()
    sig_export_jobs_changed = pyqtSignal()
    sig_bus_reset = pyqtSignal()
    sig_error = pyqtSignal(str)
    _sig_command_succeeded = pyqtSignal(object, bool)
    _sig_error_requested = pyqtSignal(str)

    def __init__(
        self,
        backend: ReplayBackend,
        settings: QtSettingsBridge,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self._backend = backend
        self._settings = settings
        self._snapshot = backend.snapshot()
        self._recordings = backend.recordings()
        self._markers = backend.markers()
        self._segments = backend.segments()
        self._export_jobs = backend.export_jobs()
        self.bus = QtBusBridge(backend.bus, parent=self)
        self._is_shutdown = False
        self._frame_pump = LatestFramePump(
            self.bus,
            thread_name="modlink.qt_bridge.replay_frames",
            read_timeout=0.1,
        )
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._poll_backend)
        self._poll_timer.start()
        self._settings.sig_setting_changed.connect(self._on_setting_changed)
        self._sig_command_succeeded.connect(
            self._handle_command_succeeded,
            Qt.ConnectionType.QueuedConnection,
        )
        self._sig_error_requested.connect(
            self._emit_error_message,
            Qt.ConnectionType.QueuedConnection,
        )
        self._reset_bus_from_backend()

    @property
    def root_dir(self) -> Path:
        return resolved_storage_root_dir(self._settings)

    @property
    def export_root_dir(self) -> Path:
        return resolved_export_root_dir(self._settings)

    def snapshot(self) -> ReplaySnapshot:
        return self._snapshot

    def recordings(self) -> tuple[ReplayRecordingSummary, ...]:
        return self._recordings

    def markers(self) -> tuple[ReplayMarker, ...]:
        return self._markers

    def segments(self) -> tuple[ReplaySegment, ...]:
        return self._segments

    def export_jobs(self) -> tuple[ExportJobSnapshot, ...]:
        return self._export_jobs

    def resync_from_backend(self) -> None:
        self._sync_snapshot()
        self._sync_recordings()
        self._sync_annotations()
        self._sync_export_jobs()

    def refresh_recordings(self) -> None:
        self._watch_command(self._backend.refresh_recordings())

    def open_recording(self, recording_path: str | Path) -> None:
        logger.debug("Bridge open_recording requested for %s", recording_path)
        self._watch_command(self._backend.open_recording(recording_path), reset_bus=True)

    def play(self) -> None:
        self._watch_command(self._backend.play())

    def pause(self) -> None:
        self._watch_command(self._backend.pause())

    def stop(self) -> None:
        self._watch_command(self._backend.stop())

    def set_speed(self, multiplier: float) -> None:
        self._watch_command(self._backend.set_speed(multiplier))

    def start_export(
        self, request: ExportRequest, output_root_dir: str | Path | None = None
    ) -> None:
        self._watch_command(self._backend.start_export(request, output_root_dir))

    def delete_recording(self, recording_id: str) -> None:
        self._watch_command(self._backend.delete_recording(recording_id), reset_bus=True)

    def seek(self, position_ns: int) -> None:
        self._watch_command(self._backend.seek(position_ns))

    def shutdown(self) -> None:
        if self._is_shutdown:
            return
        self._is_shutdown = True
        self._poll_timer.stop()
        self._frame_pump.shutdown()

    def _sync_snapshot(self) -> None:
        snapshot = self._backend.snapshot()
        if snapshot == self._snapshot:
            return
        self._snapshot = snapshot
        self.sig_snapshot_changed.emit(snapshot)

    def _sync_recordings(self) -> None:
        recordings = self._backend.recordings()
        if recordings == self._recordings:
            return
        self._recordings = recordings
        self.sig_recordings_changed.emit()

    def _sync_annotations(self) -> None:
        markers = self._backend.markers()
        segments = self._backend.segments()
        if markers == self._markers and segments == self._segments:
            return
        self._markers = markers
        self._segments = segments
        self.sig_annotations_changed.emit()

    def _sync_export_jobs(self) -> None:
        export_jobs = self._backend.export_jobs()
        if export_jobs == self._export_jobs:
            return
        self._export_jobs = export_jobs
        self.sig_export_jobs_changed.emit()

    def _poll_backend(self) -> None:
        self._sync_snapshot()
        self._sync_export_jobs()

    def _reset_bus_from_backend(self) -> None:
        logger.debug("Resetting replay bus bridge from backend descriptors")
        self.bus._set_descriptors(self._backend.bus.descriptors())
        self._frame_pump.attach_stream(
            self._backend.bus.open_frame_stream(
                maxsize=256,
                drop_policy="drop_oldest",
                consumer_name="qt_replay_bridge",
            )
        )
        self.sig_bus_reset.emit()

    @pyqtSlot(str)
    def _emit_error_message(self, message: str) -> None:
        self.sig_error.emit(message)

    @pyqtSlot(object, bool)
    def _handle_command_succeeded(self, _result: object, reset_bus: bool) -> None:
        logger.debug("Replay command completed successfully (reset_bus=%s)", reset_bus)
        if reset_bus:
            self._reset_bus_from_backend()
        self.resync_from_backend()

    @pyqtSlot(object)
    def _on_setting_changed(self, event: object) -> None:
        if getattr(event, "key", None) == STORAGE_ROOT_DIR_KEY:
            self.refresh_recordings()

    def _watch_command(self, future: Future[object], *, reset_bus: bool = False) -> None:
        def _notify_completed(completed: Future[object]) -> None:
            try:
                result = completed.result()
            except CancelledError:
                logger.warning("Replay command cancelled")
                self._sig_error_requested.emit("REPLAY_COMMAND_CANCELLED")
                return
            except Exception as exc:
                logger.exception("Replay command failed")
                self._sig_error_requested.emit(str(exc))
                return
            self._sig_command_succeeded.emit(result, reset_bus)

        if future.done():
            _notify_completed(future)
            return
        future.add_done_callback(_notify_completed)
