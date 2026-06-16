from __future__ import annotations

import logging
from typing import Literal

from PyQt6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import InfoBar, InfoBarPosition

from modlink_core.models import ReplaySnapshot
from modlink_ui.bridge import QtModLinkBridge

from .export_dialog import ExportDialog
from .player_page import ReplayPlayerPage
from .recordings_page import ReplayRecordingsPage

type ReplayRoute = Literal["recordings", "player"]

logger = logging.getLogger(__name__)


class _CurrentReplayStack(QStackedWidget):
    def sizeHint(self):
        w = self.currentWidget()
        return w.sizeHint() if w else super().sizeHint()

    def minimumSizeHint(self):
        w = self.currentWidget()
        return w.minimumSizeHint() if w else super().minimumSizeHint()


class ReplayPage(QWidget):
    def __init__(self, engine: QtModLinkBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setObjectName("replay-page")
        self._replay = engine.replay
        self._route: ReplayRoute = "recordings"
        self._pending_open_recording_path: str | None = None

        # --- Pages ---
        self._page_stack = _CurrentReplayStack(self)
        self._recordings_page = ReplayRecordingsPage(self._page_stack)
        self._player_page = ReplayPlayerPage(self._replay, engine.settings, self._page_stack)
        self._page_stack.addWidget(self._recordings_page)
        self._page_stack.addWidget(self._player_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._page_stack, 1)

        # --- User actions → bridge commands ---
        self._recordings_page.sig_open_recording_requested.connect(self._open_recording)
        self._recordings_page.sig_refresh_requested.connect(self._replay.refresh_recordings)
        self._recordings_page.sig_delete_recording_requested.connect(self._replay.delete_recording)
        self._recordings_page.sig_export_selected_requested.connect(self._on_batch_export_requested)
        self._player_page.sig_show_recordings_requested.connect(self._show_recordings_page)
        self._player_page.sig_show_export_requested.connect(self._on_player_export_requested)
        self._player_page.sig_play_requested.connect(self._replay.play)
        self._player_page.sig_pause_requested.connect(self._replay.pause)
        self._player_page.sig_reset_requested.connect(self._replay.stop)
        self._player_page.sig_reset_requested.connect(self._player_page.preview_panel.clear_plots)
        self._player_page.sig_speed_changed.connect(self._replay.set_speed)
        self._player_page.sig_seek_requested.connect(self._replay.seek)
        self._player_page.sig_delete_recording_requested.connect(self._replay.delete_recording)

        # --- Bridge state → UI updates ---
        self._replay.sig_snapshot_changed.connect(self._on_snapshot_changed)
        self._replay.sig_recordings_changed.connect(self._reload_recordings)
        self._replay.sig_annotations_changed.connect(self._reload_annotations)
        self._replay.sig_export_jobs_changed.connect(self._on_export_jobs_changed)
        self._replay.sig_bus_reset.connect(self._on_bus_reset)
        self._replay.sig_error.connect(self._on_error)

        # --- Initial sync ---
        self._on_snapshot_changed(self._replay.snapshot())
        self._reload_recordings()
        self._reload_annotations()
        self._set_route("recordings")
        self._replay.refresh_recordings()

    # --- Routing ---

    def _set_route(self, route: ReplayRoute) -> None:
        if route == "player" and self._replay.snapshot().recording_id is None:
            route = "recordings"
        target = {"recordings": self._recordings_page, "player": self._player_page}[route]
        if self._route == route and self._page_stack.currentWidget() is target:
            return
        self._route = route
        self._page_stack.setCurrentWidget(target)
        self._page_stack.updateGeometry()
        self.updateGeometry()

    def _show_recordings_page(self) -> None:
        self._set_route("recordings")

    def _show_player_page(self) -> None:
        self._set_route("player")

    # --- Bridge state handlers ---

    def _on_snapshot_changed(self, snapshot: object) -> None:
        if not isinstance(snapshot, ReplaySnapshot):
            snapshot = self._replay.snapshot()
        self._player_page.apply_snapshot(snapshot)
        self._finish_pending_open_if_ready(snapshot)
        if snapshot.recording_id is None and self._route == "player":
            self._set_route("recordings")

    def _reload_recordings(self) -> None:
        self._recordings_page.reload_recordings(self._replay.recordings())

    def _reload_annotations(self) -> None:
        self._player_page.reload_annotations(
            self._replay.markers(),
            self._replay.segments(),
            self._replay.snapshot(),
        )
        # Re-apply snapshot so panel C picks up fresh markers immediately.
        self._on_snapshot_changed(self._replay.snapshot())

    def _on_export_jobs_changed(self) -> None:
        """Show toast when an export job completes or fails."""
        jobs = self._replay.export_jobs()
        if not jobs:
            return
        latest = jobs[-1]
        parent = self.window() if isinstance(self.window(), QWidget) else self
        if latest.state == "completed" and latest.output_path:
            InfoBar.success(
                title="导出完成",
                content=str(latest.output_path),
                duration=5000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=parent,
            )
        elif latest.state == "failed" and latest.error:
            InfoBar.error(
                title="导出失败",
                content=latest.error,
                duration=5000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=parent,
            )

    def _on_bus_reset(self) -> None:
        self._finish_pending_open_if_ready(self._replay.snapshot())

    # --- Open recording flow ---

    def _open_recording(self, recording_path: str) -> None:
        self._pending_open_recording_path = recording_path
        self._replay.open_recording(recording_path)

    def _finish_pending_open_if_ready(self, snapshot: ReplaySnapshot) -> None:
        if self._pending_open_recording_path is None:
            return
        if not snapshot.recording_path:
            return
        from pathlib import Path

        if Path(snapshot.recording_path) != Path(self._pending_open_recording_path):
            return
        self._pending_open_recording_path = None
        self._set_route("player")

    # --- Export (dialog-based) ---

    def _on_player_export_requested(self) -> None:
        """Export the currently-open recording from the player page."""
        snapshot = self._replay.snapshot()
        if snapshot.recording_id is None:
            return
        self._open_export_dialog([snapshot.recording_id])

    def _on_batch_export_requested(self, recording_ids: list) -> None:
        """Export selected recordings from the list page."""
        if not recording_ids:
            return
        self._open_export_dialog(list(recording_ids))

    def _open_export_dialog(self, recording_ids: list[str]) -> None:
        """Open the export dialog for the given recordings."""
        dialog = ExportDialog(
            recording_ids=recording_ids,
            root_dir=self._replay.root_dir,
            parent=self.window(),
        )
        if dialog.exec():
            request = dialog.build_request()
            if request is not None:
                self._replay.start_export(request, dialog.selected_output_dir())
                parent = self.window() if isinstance(self.window(), QWidget) else self
                InfoBar.success(
                    title="导出已开始",
                    content=f"正在导出 {len(recording_ids)} 条录制...",
                    duration=3000,
                    position=InfoBarPosition.TOP_RIGHT,
                    parent=parent,
                )

    # --- Error ---

    def _on_error(self, message: str) -> None:
        self._pending_open_recording_path = None
        parent = self.window() if isinstance(self.window(), QWidget) else self
        InfoBar.error(
            title="回放错误",
            content=message,
            duration=4500,
            position=InfoBarPosition.TOP_RIGHT,
            parent=parent,
        )
