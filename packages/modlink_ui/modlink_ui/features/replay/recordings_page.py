from __future__ import annotations

from datetime import UTC

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    ListWidget,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    RoundMenu,
    SimpleCardWidget,
    StrongBodyLabel,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from modlink_core.models import ReplayRecordingSummary
from modlink_ui.shared import BasePage, EmptyStateMessage


def _format_tooltip(summary: ReplayRecordingSummary) -> str:
    """Format a multi-line tooltip for a recording list item."""
    title = (summary.recording_label or "").strip() or summary.recording_id
    lines = [title, "─" * min(len(title) + 4, 30)]

    if summary.duration_ns is not None:
        total_seconds = summary.duration_ns // 1_000_000_000
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        lines.append(f"时长: {hours:02d}:{minutes:02d}:{seconds:02d}")

    if summary.total_frames is not None:
        stream_count = len(summary.stream_ids)
        stream_text = f"{stream_count} {'stream' if stream_count == 1 else 'streams'}"
        lines.append(f"帧数: {summary.total_frames:,}（{stream_text}）")

    if summary.started_at_ns is not None:
        from datetime import datetime

        dt = datetime.fromtimestamp(summary.started_at_ns / 1_000_000_000, tz=UTC)
        local_dt = dt.astimezone()
        lines.append(f"录制时间: {local_dt.strftime('%Y-%m-%d %H:%M:%S')}")

    if summary.status == "failed":
        lines.append("状态: 失败")

    if summary.session_name:
        lines.append(f"Session: {summary.session_name}")
    if summary.experiment_name:
        lines.append(f"Experiment: {summary.experiment_name}")

    return "\n".join(lines)


class ReplayRecordingsPanel(SimpleCardWidget):
    sig_delete_recording_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.recording_list = ListWidget(self)
        self.recording_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.recording_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.recording_list.customContextMenuRequested.connect(self._show_context_menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        layout.addWidget(StrongBodyLabel("Recordings", self))
        layout.addWidget(self.recording_list, 1)

    def selected_recording_ids(self) -> list[str]:
        """Return recording_ids of all selected items."""
        ids = []
        for item in self.recording_list.selectedItems():
            rec_id = item.data(Qt.ItemDataRole.UserRole)
            if rec_id:
                ids.append(rec_id)
        return ids

    def selected_recording_id(self) -> str | None:
        item = self.recording_list.currentItem()
        if item is None:
            return None
        recording_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(recording_id, str) and recording_id:
            return recording_id
        return None

    def selected_recording_path(self) -> str | None:
        item = self.recording_list.currentItem()
        if item is None:
            return None
        recording_path = item.data(Qt.ItemDataRole.UserRole + 1)
        if isinstance(recording_path, str) and recording_path:
            return recording_path
        return None

    def reload_recordings(self, recordings: tuple[ReplayRecordingSummary, ...]) -> None:
        selected_recording_id = self.selected_recording_id()
        self.recording_list.clear()
        for summary in recordings:
            title = (summary.recording_label or "").strip() or summary.recording_id
            stream_count = len(summary.stream_ids)
            stream_text = f"{stream_count} {'stream' if stream_count == 1 else 'streams'}"
            item_text = f"{title} · {stream_text}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, summary.recording_id)
            item.setData(Qt.ItemDataRole.UserRole + 1, summary.recording_path)
            item.setToolTip(_format_tooltip(summary))
            self.recording_list.addItem(item)
            if summary.recording_id == selected_recording_id:
                self.recording_list.setCurrentItem(item)

    def _show_context_menu(self, position: QPoint) -> None:
        item = self.recording_list.itemAt(position)
        if item is None:
            return
        recording_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(recording_id, str) or not recording_id:
            return
        # Selecting the right-clicked row matches OS-native list behaviour
        # and makes the confirm dialog refer to the row the user just acted on.
        self.recording_list.setCurrentItem(item)

        menu = RoundMenu(parent=self.recording_list)
        delete_action = Action(FIF.DELETE, "删除", menu)
        delete_action.triggered.connect(
            lambda: self.sig_delete_recording_requested.emit(recording_id)
        )
        menu.addAction(delete_action)
        menu.exec(self.recording_list.viewport().mapToGlobal(position))


class ReplayRecordingsPage(BasePage):
    sig_open_recording_requested = pyqtSignal(str)
    sig_refresh_requested = pyqtSignal()
    sig_delete_recording_requested = pyqtSignal(str)
    sig_export_selected_requested = pyqtSignal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            page_key="replay-recordings-page",
            title="回放",
            description="浏览已有 recordings，打开其中一条进入回放或导出工作台。右键单条可删除。",
            parent=parent,
        )
        self._open_button = PrimaryPushButton("打开", self)
        self._open_button.setIcon(FIF.FOLDER)
        self._refresh_button = PushButton("刷新", self)
        self._refresh_button.setIcon(FIF.SYNC)
        self._export_button = PushButton("导出", self)
        self._export_button.setIcon(FIF.SAVE)
        self._export_button.setVisible(False)
        self._export_button.setMinimumWidth(88)
        for button in (self._open_button, self._refresh_button):
            button.setMinimumWidth(88)
            self.header_action_layout.addWidget(button)

        self.empty_state = EmptyStateMessage(
            "当前还没有发现 recording",
            "点击“刷新”重新扫描 storage.root_dir/recordings。",
            self.scroll_widget,
        )
        self.recordings_panel = ReplayRecordingsPanel(self.scroll_widget)
        self.content_layout.addWidget(self.empty_state)
        self.content_layout.addWidget(self.recordings_panel, 1)

        self.recording_list.itemDoubleClicked.connect(lambda _item: self._emit_open_requested())
        self.open_button.clicked.connect(self._emit_open_requested)
        self.refresh_button.clicked.connect(self.sig_refresh_requested.emit)
        self.recordings_panel.sig_delete_recording_requested.connect(self._confirm_and_emit_delete)
        self.recording_list.itemSelectionChanged.connect(self._on_selection_changed)
        self._export_button.clicked.connect(self._emit_export_selected)

    @property
    def recording_list(self) -> ListWidget:
        return self.recordings_panel.recording_list

    @property
    def open_button(self) -> PrimaryPushButton:
        return self._open_button

    @property
    def refresh_button(self) -> PushButton:
        return self._refresh_button

    @property
    def export_button(self) -> PushButton:
        return self._export_button

    def selected_recording_id(self) -> str | None:
        return self.recordings_panel.selected_recording_id()

    def selected_recording_path(self) -> str | None:
        return self.recordings_panel.selected_recording_path()

    def reload_recordings(self, recordings: tuple[ReplayRecordingSummary, ...]) -> None:
        self.recordings_panel.reload_recordings(recordings)
        self.empty_state.setVisible(not recordings)

    def _emit_open_requested(self) -> None:
        recording_path = self.selected_recording_path()
        if recording_path is not None:
            self.sig_open_recording_requested.emit(recording_path)

    def _confirm_and_emit_delete(self, recording_id: str) -> None:
        parent = self.window() if isinstance(self.window(), QWidget) else self
        prompt = MessageBox(
            "删除 recording",
            f"确定要删除 recording {recording_id} 吗？此操作无法撤销，导出文件不会被一同删除。",
            parent,
        )
        if prompt.exec():
            self.sig_delete_recording_requested.emit(recording_id)

    def _on_selection_changed(self) -> None:
        selected = self.recordings_panel.selected_recording_ids()
        count = len(selected)
        if count > 0 and self._export_button.parent() is self:
            # Lazily add to header layout on first selection
            if self.header_action_layout.indexOf(self._export_button) == -1:
                self.header_action_layout.addWidget(self._export_button)
        self._export_button.setVisible(count > 0)
        if count > 0:
            self._export_button.setText(f"导出 ({count})")

    def _emit_export_selected(self) -> None:
        selected = self.recordings_panel.selected_recording_ids()
        if selected:
            self.sig_export_selected_requested.emit(selected)


__all__ = ["ReplayRecordingsPage"]
