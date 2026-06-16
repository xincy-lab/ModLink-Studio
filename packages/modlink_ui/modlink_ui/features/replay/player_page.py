from __future__ import annotations

import time

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    SimpleCardWidget,
    Slider,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from modlink_core.models import ReplaySnapshot
from modlink_sdk import FrameEnvelope
from modlink_ui.bridge import QtReplayBridge, QtSettingsBridge
from modlink_ui.shared import BasePage, EmptyStateMessage
from modlink_ui.shared.preview.cards import DetachableStreamPreviewCard


def format_time_ns(value: int) -> str:
    total_ms = max(0, int(value // 1_000_000))
    total_seconds, millis = divmod(total_ms, 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def parse_time_text(text: str) -> int | None:
    """Parse '01:23.456' or '01:02:03.456' into nanoseconds."""
    text = text.strip()
    if not text:
        return None
    try:
        parts = text.split(":")
        if len(parts) == 3:
            hours, minutes = int(parts[0]), int(parts[1])
            sec_parts = parts[2].split(".")
        elif len(parts) == 2:
            hours = 0
            minutes = int(parts[0])
            sec_parts = parts[1].split(".")
        elif len(parts) == 1:
            hours, minutes = 0, 0
            sec_parts = parts[0].split(".")
        else:
            return None
        seconds = int(sec_parts[0])
        millis = int(sec_parts[1]) if len(sec_parts) > 1 else 0
        total_ms = ((hours * 3600 + minutes * 60 + seconds) * 1000) + millis
        return total_ms * 1_000_000
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Preview panel — shows stream cards or empty state
# ---------------------------------------------------------------------------


class ReplayPreviewPanel(QWidget):
    _empty_minimum_height = 360

    def __init__(
        self,
        replay: QtReplayBridge,
        settings: QtSettingsBridge,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self._replay = replay
        self._settings = settings
        self._cards: dict[str, DetachableStreamPreviewCard] = {}
        self.setObjectName("replay-preview-panel")
        self.setMinimumHeight(self._empty_minimum_height)

        self.empty_state = EmptyStateMessage(
            "当前还没有打开 recording",
            "先从 recordings 页打开一条 recording，再进入这里查看流预览。",
            self,
        )
        self.empty_state_container = QWidget(self)
        empty_layout = QVBoxLayout(self.empty_state_container)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_state, 0, Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch(1)

        self.cards_container = QWidget(self)
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(14)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.empty_state_container, 1)
        layout.addWidget(self.cards_container, 1)

        self._replay.bus.sig_frame.connect(self._on_frame)
        self._replay.sig_bus_reset.connect(self.rebuild_from_bus)
        self.rebuild_from_bus()

    def rebuild_from_bus(self) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if (w := item.widget()) is not None:
                w.deleteLater()
        self._cards.clear()

        descriptors = sorted(
            self._replay.bus.descriptors().values(),
            key=lambda d: d.display_name or d.stream_id,
        )
        for descriptor in descriptors:
            card = DetachableStreamPreviewCard(descriptor, self._settings, self.cards_container)
            self._cards[descriptor.stream_id] = card
            self.cards_layout.addWidget(card)
        self._sync_visibility()

    def clear_plots(self) -> None:
        """Clear all plotted data in preview cards (e.g. on reset)."""
        for card in self._cards.values():
            card.card.stream_view.clear()

    def _on_frame(self, frame: FrameEnvelope) -> None:
        card = self._cards.get(frame.stream_id)
        if card is None:
            if self._replay.bus.descriptor(frame.stream_id) is None:
                return
            self.rebuild_from_bus()
            card = self._cards.get(frame.stream_id)
            if card is None:
                return
        card.push_frame(frame)

    def _sync_visibility(self) -> None:
        has_cards = bool(self._cards)
        self.empty_state_container.setVisible(not has_cards)
        self.cards_container.setVisible(has_cards)
        self._sync_minimum_height()

    def _sync_minimum_height(self) -> None:
        if self._cards:
            content_height = max(
                self.cards_container.minimumSizeHint().height(),
                self.cards_container.sizeHint().height(),
            )
            minimum_height = max(self._empty_minimum_height, content_height)
        else:
            minimum_height = self._empty_minimum_height
        if self.minimumHeight() != minimum_height:
            self.setMinimumHeight(minimum_height)
        self.updateGeometry()
        parent = self.parentWidget()
        while parent is not None:
            if (lay := parent.layout()) is not None:
                lay.invalidate()
            parent.updateGeometry()
            parent = parent.parentWidget()


# ---------------------------------------------------------------------------
# Player page — transport bar + preview, modeled after a standard media player
# ---------------------------------------------------------------------------


class ReplayPlayerPage(BasePage):
    sig_show_recordings_requested = pyqtSignal()
    sig_show_export_requested = pyqtSignal()
    sig_play_requested = pyqtSignal()
    sig_pause_requested = pyqtSignal()
    sig_reset_requested = pyqtSignal()
    sig_speed_changed = pyqtSignal(float)
    # qint64 is required: nanosecond positions exceed C int32 range (~2.147s)
    # for any recording longer than ~2 seconds. Plain int truncates and wraps
    # to negative, which the backend then clamps to 0 — every seek silently
    # plays from the start. See https://doc.qt.io/qt-6/qmetatype.html
    sig_seek_requested = pyqtSignal("qint64")
    sig_delete_recording_requested = pyqtSignal(str)

    def __init__(
        self,
        replay: QtReplayBridge,
        settings: QtSettingsBridge,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            page_key="replay-player-page",
            title="回放",
            description="预览流、浏览标注并控制播放。",
            parent=parent,
        )
        self._snapshot = ReplaySnapshot(
            state="idle",
            is_started=False,
            recording_id=None,
            recording_path=None,
            position_ns=0,
            duration_ns=0,
            speed_multiplier=1.0,
        )
        self._user_dragging = False
        # Time-based seek suppression. After the user commits a seek (release or
        # track-click), we suppress snapshot-driven slider/label updates for a
        # short window so a stale snapshot polled before the backend processed
        # the seek does NOT snap the slider back. We use a deadline rather than
        # a position-match because once playback resumes the backend position
        # advances past the seek target, and any match-based guard would
        # permanently lock the sync.
        self._seek_suppress_until_ns: int = 0

        # --- Header buttons ---
        self.recordings_route_button = PushButton("列表", self)
        self.recordings_route_button.setIcon(FIF.LIBRARY)
        self.export_route_button = PushButton("导出", self)
        self.export_route_button.setIcon(FIF.SAVE)
        self.delete_button = PushButton("删除", self)
        self.delete_button.setIcon(FIF.DELETE)
        for btn in (self.recordings_route_button, self.export_route_button, self.delete_button):
            btn.setMinimumWidth(88)
            self.header_action_layout.addWidget(btn)

        # --- Preview panel (stream cards) ---
        self.preview_panel = ReplayPreviewPanel(replay, settings, self.scroll_widget)
        self.content_layout.addWidget(self.preview_panel)

        # Spacer to reserve room for the floating transport bar
        self._floating_spacer = QWidget(self.scroll_widget)
        self._floating_spacer.setFixedHeight(0)
        self.content_layout.addWidget(self._floating_spacer)

        # --- Transport bar (floating, like a media player control bar) ---
        self.transport_bar = SimpleCardWidget(self)
        self.transport_bar.setObjectName("replay-transport-bar")
        self.transport_bar.setBorderRadius(18)
        self.transport_bar.hide()

        # Slider — range 0..10000 for finer granularity
        self.slider = Slider(Qt.Orientation.Horizontal, self.transport_bar)
        self.slider.setRange(0, 10000)
        self.slider.setValue(0)

        # Controls row
        self.play_pause_button = PrimaryPushButton("播放", self.transport_bar)
        self.play_pause_button.setIcon(FIF.PLAY_SOLID)
        self.play_pause_button.setToolTip("播放")
        self.play_pause_button.setAccessibleName("播放")

        self.reset_button = PushButton("复位", self.transport_bar)
        self.reset_button.setIcon(FIF.SYNC)
        self.reset_button.setToolTip("复位")
        self.reset_button.setAccessibleName("复位")

        # Position label — absolutely centered over the controls row
        self.position_label = CaptionLabel("00:00.000 / 00:00.000", self.transport_bar)
        self.position_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Speed combo — far right
        self.speed_combo = ComboBox(self.transport_bar)
        self.speed_combo.addItem("1x", userData=1.0)
        self.speed_combo.addItem("2x", userData=2.0)
        self.speed_combo.addItem("4x", userData=4.0)

        # Layout: slider on top, controls row below
        transport_layout = QVBoxLayout(self.transport_bar)
        transport_layout.setContentsMargins(18, 14, 18, 14)
        transport_layout.setSpacing(8)
        transport_layout.addWidget(self.slider)

        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(8)
        controls_row.addWidget(self.play_pause_button)
        controls_row.addWidget(self.reset_button)
        controls_row.addStretch(1)
        controls_row.addWidget(BodyLabel("倍速", self.transport_bar))
        controls_row.addWidget(self.speed_combo)
        transport_layout.addLayout(controls_row)

        # --- Signals ---
        self.play_pause_button.clicked.connect(self._on_play_pause_clicked)
        self.reset_button.clicked.connect(self._on_reset_clicked)
        self.speed_combo.currentIndexChanged.connect(self._on_speed_changed)
        self.recordings_route_button.clicked.connect(self.sig_show_recordings_requested.emit)
        self.export_route_button.clicked.connect(self.sig_show_export_requested.emit)
        self.delete_button.clicked.connect(self._on_delete_clicked)

        # Slider: track press/release to know when user is dragging
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.slider.valueChanged.connect(self._on_slider_value_changed)
        self.slider.clicked.connect(self._on_slider_clicked)

        # Event filter for floating bar positioning
        self.scroll_area.viewport().installEventFilter(self)
        self.transport_bar.installEventFilter(self)

    # --- Public interface (called by ReplayPage) ---

    def apply_snapshot(self, snapshot: ReplaySnapshot) -> None:
        self._snapshot = snapshot
        self._sync_buttons(snapshot)
        if self._should_sync_progress(snapshot):
            self._sync_progress(snapshot)
        self._sync_header(snapshot)
        self._sync_floating_transport_bar()

    def reload_annotations(
        self,
        markers: tuple,
        segments: tuple,
        snapshot: ReplaySnapshot,
    ) -> None:
        if self._should_sync_progress(snapshot):
            self._sync_progress(snapshot)
        self._sync_floating_transport_bar()

    def selected_speed(self) -> float | None:
        value = self.speed_combo.currentData()
        return float(value) if isinstance(value, (float, int)) else None

    # --- Slider interaction ---
    #
    # qfluentwidgets.Slider emits the following signals we care about:
    #   - sliderPressed:  user pressed the handle (NOT track-click)
    #   - sliderReleased: user released the handle
    #   - valueChanged:   emitted on any value change, including programmatic setValue()
    #   - clicked:        emitted on track-click (in mousePressEvent), NOT on handle press
    #
    # We seek only on commit events (release / track-click), never during the drag
    # itself. Emitting mid-drag floods the backend with throwaway seeks that race
    # against the poll-timer snapshot sync and visually snap the handle back.

    def _on_slider_pressed(self) -> None:
        self._user_dragging = True

    def _on_slider_released(self) -> None:
        # Capture target before clearing the drag flag so any snapshot sync
        # arriving in this window stays gated by _user_dragging.
        target_value = self.slider.value()
        self._seek_to_slider_value(target_value)
        self._user_dragging = False

    def _on_slider_clicked(self, value: int) -> None:
        # Track click — qfluentwidgets emits this only for track clicks
        # (mousePressEvent has already called setValue, so the slider visual
        # has snapped to `value`).
        self._seek_to_slider_value(value)

    def _on_slider_value_changed(self, value: int) -> None:
        if not self._user_dragging:
            return
        # Live-update the position label while the user drags. Do NOT emit
        # a seek here — we only commit on release.
        duration_ns = self._snapshot.duration_ns
        if duration_ns <= 0:
            return
        position_ns = int((value / 10000) * duration_ns)
        self.position_label.setText(
            f"{format_time_ns(position_ns)} / {format_time_ns(duration_ns)}"
        )

    def _seek_to_slider_value(self, value: int) -> None:
        duration_ns = self._snapshot.duration_ns
        if duration_ns <= 0:
            return
        position_ns = int((value / 10000) * duration_ns)
        # Update the label immediately so the user sees the seek take effect,
        # even before the backend confirms. Without this, the label stays at
        # whatever the last snapshot showed (typically 00:00.000) until the
        # next non-suppressed sync, which can feel like a frozen UI.
        self.position_label.setText(
            f"{format_time_ns(position_ns)} / {format_time_ns(duration_ns)}"
        )
        # Suppress snapshot-driven slider syncs for a short window. The poll
        # timer fires every 100ms and the backend command queue + Qt signal
        # round-trip can lag behind. 300ms is enough for the typical command
        # path; any longer and the user notices a stuck slider.
        self._seek_suppress_until_ns = time.monotonic_ns() + 300_000_000
        self.sig_seek_requested.emit(position_ns)

    # --- State sync ---

    def _should_sync_progress(self, snapshot: ReplaySnapshot) -> bool:
        # Don't fight an in-progress drag.
        if self._user_dragging:
            return False
        # Suppress snapshot-driven slider snap-back briefly after a seek.
        # Time-based so it auto-expires no matter what the backend reports.
        if time.monotonic_ns() < self._seek_suppress_until_ns:
            return False
        return True

    def _sync_progress(self, snapshot: ReplaySnapshot) -> None:
        """Update slider position and time label from backend snapshot."""
        duration_ns = max(0, snapshot.duration_ns)
        position_ns = min(max(0, snapshot.position_ns), duration_ns)
        self.position_label.setText(
            f"{format_time_ns(position_ns)} / {format_time_ns(duration_ns)}"
        )
        if duration_ns > 0:
            self.slider.setValue(int((position_ns / duration_ns) * 10000))
        else:
            self.slider.setValue(0)

    def _sync_buttons(self, snapshot: ReplaySnapshot) -> None:
        """Update button states from snapshot."""
        has_recording = snapshot.recording_id is not None

        # Play/pause toggle button
        if snapshot.state == "playing":
            self.play_pause_button.setIcon(FIF.PAUSE_BOLD)
            self.play_pause_button.setText("暂停")
            self.play_pause_button.setToolTip("暂停")
            self.play_pause_button.setAccessibleName("暂停")
        else:
            self.play_pause_button.setIcon(FIF.PLAY_SOLID)
            self.play_pause_button.setText("播放")
            self.play_pause_button.setToolTip("播放")
            self.play_pause_button.setAccessibleName("播放")
        self.play_pause_button.setEnabled(has_recording)

        # Reset button — always enabled when a recording is loaded
        self.reset_button.setEnabled(has_recording)

        self.export_route_button.setEnabled(has_recording)
        self.delete_button.setEnabled(has_recording)

    def _sync_header(self, snapshot: ReplaySnapshot) -> None:
        recording_id = _format_recording_badge(snapshot.recording_id)
        self.description_label.setText(
            f"当前 recording：{recording_id} · 预览流、浏览标注并控制播放。"
        )

    # --- Button handlers ---

    def _on_play_pause_clicked(self) -> None:
        if self._snapshot.state == "playing":
            self.sig_pause_requested.emit()
        else:
            self.sig_play_requested.emit()

    def _on_reset_clicked(self) -> None:
        self.sig_reset_requested.emit()

    def _on_speed_changed(self) -> None:
        value = self.selected_speed()
        if value is not None:
            self.sig_speed_changed.emit(value)

    def _on_delete_clicked(self) -> None:
        recording_id = self._snapshot.recording_id
        if not recording_id:
            return
        parent = self.window() if isinstance(self.window(), QWidget) else self
        prompt = MessageBox(
            "删除 recording",
            f"确定要删除 recording {recording_id} 吗？此操作无法撤销，导出文件不会被一同删除。",
            parent,
        )
        if prompt.exec():
            self.sig_delete_recording_requested.emit(recording_id)

    # --- Floating transport bar positioning ---

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched in (self.scroll_area.viewport(), self.transport_bar):
            if event.type() in (
                QEvent.Type.Resize,
                QEvent.Type.Show,
                QEvent.Type.Hide,
                QEvent.Type.LayoutRequest,
            ):
                QTimer.singleShot(0, self._sync_floating_transport_bar)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_floating_transport_bar()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_floating_transport_bar)

    def hideEvent(self, event) -> None:
        self.transport_bar.hide()
        super().hideEvent(event)

    def _sync_floating_transport_bar(self) -> None:
        viewport = self.scroll_area.viewport()
        if not self.isVisible() or not viewport.isVisible():
            self.transport_bar.hide()
            return

        panel_height = max(
            self.transport_bar.minimumSizeHint().height(),
            self.transport_bar.sizeHint().height(),
        )
        reserve_height = panel_height + 24
        if self._floating_spacer.height() != reserve_height:
            self._floating_spacer.setFixedHeight(reserve_height)

        viewport_top_left = viewport.mapTo(self, QPoint(0, 0))
        side_margin = 16
        bottom_margin = 12
        max_panel_width = 1160
        panel_width = min(max_panel_width, max(420, viewport.width() - side_margin * 2))
        panel_x = viewport_top_left.x() + max(0, (viewport.width() - panel_width) // 2)
        panel_y = viewport_top_left.y() + viewport.height() - panel_height - bottom_margin

        self.transport_bar.setGeometry(panel_x, panel_y, panel_width, panel_height)
        if not self.transport_bar.isVisible():
            self.transport_bar.show()
        self.transport_bar.raise_()

        # Center position label absolutely within the transport bar
        self.position_label.adjustSize()
        label_x = (panel_width - self.position_label.width()) // 2
        label_y = (
            self.slider.geometry().bottom()
            + (panel_height - self.slider.geometry().bottom() - self.position_label.height()) // 2
        )
        self.position_label.move(label_x, label_y)
        self.position_label.raise_()


def _format_recording_badge(recording_id: str | None) -> str:
    if not recording_id:
        return "未打开 recording"
    if len(recording_id) <= 26:
        return recording_id
    return f"{recording_id[:14]}...{recording_id[-8:]}"


__all__ = ["ReplayPlayerPage"]
