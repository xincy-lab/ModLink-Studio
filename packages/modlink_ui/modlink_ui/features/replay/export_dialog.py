from __future__ import annotations

import re
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    ComboBox,
    LineEdit,
    MessageBoxBase,
    PushButton,
    SimpleCardWidget,
    StrongBodyLabel,
    SubtitleLabel,
)

from modlink_core.replay.export_request import ExportMode, ExportRequest, StreamSelection
from modlink_core.replay.store import RecordingStore
from modlink_sdk import StreamDescriptor

_FORMAT_OPTIONS_BY_PAYLOAD: dict[str, tuple[tuple[str, str], ...]] = {
    "signal": (("signal_csv", "CSV"), ("signal_npz", "NPZ")),
    "raster": (
        ("raster_waterfall_png", "Waterfall PNG"),
        ("raster_waterfall_segmented_zip", "Segmented ZIP"),
        ("raster_npz", "NPZ"),
    ),
    "field": (("field_npz", "NPZ"), ("field_mp4", "MP4"), ("field_png_zip", "PNG ZIP")),
    "video": (("video_mp4", "MP4"), ("video_png_zip", "PNG ZIP")),
}

_HMS_PATTERN = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?$")


def _parse_hms_to_ns(text: str) -> int | None:
    """Parse "HH:MM:SS.mmm" → nanoseconds. Returns None on error."""
    m = _HMS_PATTERN.match(text.strip())
    if not m:
        return None
    h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
    ms_str = m.group(4) or "0"
    ms = int(ms_str.ljust(3, "0")[:3])
    total_ms = ((h * 3600 + mi * 60 + s) * 1000) + ms
    return total_ms * 1_000_000


class ExportDialog(MessageBoxBase):
    def __init__(self, recording_ids: list[str], root_dir: Path, parent: QWidget | None = None):
        super().__init__(parent=parent)
        self._recording_ids = recording_ids
        self._root_dir = root_dir
        self._output_dir: str | None = None
        self._stream_rows: list[tuple[StreamDescriptor, CheckBox, ComboBox]] = []

        # Load descriptors — one row per unique stream_id across all recordings
        store = RecordingStore(root_dir)
        seen_ids: set[str] = set()
        all_descriptors: list[StreamDescriptor] = []
        for rec_id in recording_ids:
            reader = store.open(rec_id)
            for sid, desc in reader.descriptors().items():
                if sid not in seen_ids:
                    seen_ids.add(sid)
                    all_descriptors.append(desc)

        self._build_ui(all_descriptors)

        self.yesButton.setText("开始导出")
        self.cancelButton.setText("取消")
        self.widget.setMinimumWidth(520)
        self.setClosableOnMaskClicked(True)

    def _build_ui(self, descriptors: list[StreamDescriptor]) -> None:
        # Title
        self.viewLayout.addWidget(SubtitleLabel("导出"))

        # Multi-recording list
        if len(self._recording_ids) >= 2:
            ids_text = "、".join(self._recording_ids)
            self.viewLayout.addWidget(
                BodyLabel(f"已选择 {len(self._recording_ids)} 个录制：{ids_text}")
            )

        # Streams card
        streams_card = SimpleCardWidget()
        streams_card.setBorderRadius(8)
        streams_layout = QVBoxLayout(streams_card)
        streams_layout.setContentsMargins(20, 16, 20, 16)
        streams_layout.setSpacing(10)
        streams_layout.addWidget(StrongBodyLabel("流选择"))

        for desc in descriptors:
            options = _FORMAT_OPTIONS_BY_PAYLOAD.get(desc.payload_type, ())
            display = desc.display_name or f"{desc.device_id} / {desc.stream_key}"
            cb = CheckBox(f"{display} ({desc.payload_type})")
            cb.setToolTip(desc.stream_id)
            cb.setChecked(True)
            combo = ComboBox()
            for fmt_id, label in options:
                combo.addItem(label, userData=fmt_id)
            if options:
                combo.setCurrentIndex(0)
            else:
                combo.setEnabled(False)
                cb.setChecked(False)
                cb.setEnabled(False)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            row.addWidget(cb, 1)
            row.addWidget(combo, 0, Qt.AlignmentFlag.AlignRight)
            streams_layout.addLayout(row)
            self._stream_rows.append((desc, cb, combo))
        self.viewLayout.addWidget(streams_card)

        # Time range card (single recording only)
        self._time_range_enabled = CheckBox("裁剪时间范围")
        self._time_range_enabled.setChecked(False)
        self._time_start_edit = LineEdit()
        self._time_start_edit.setPlaceholderText("00:00:00.000")
        self._time_end_edit = LineEdit()
        self._time_end_edit.setPlaceholderText("00:01:00.000")
        if len(self._recording_ids) == 1:
            time_card = SimpleCardWidget()
            time_card.setBorderRadius(8)
            time_layout = QVBoxLayout(time_card)
            time_layout.setContentsMargins(20, 16, 20, 16)
            time_layout.setSpacing(8)
            time_layout.addWidget(StrongBodyLabel("时间范围"))
            time_layout.addWidget(self._time_range_enabled)
            time_row = QHBoxLayout()
            time_row.setSpacing(8)
            time_row.addWidget(self._time_start_edit)
            time_row.addWidget(BodyLabel("—"))
            time_row.addWidget(self._time_end_edit)
            self._time_range_row_widget = QWidget()
            self._time_range_row_widget.setLayout(time_row)
            self._time_range_row_widget.setVisible(False)
            time_layout.addWidget(self._time_range_row_widget)
            self._time_range_enabled.stateChanged.connect(
                lambda state: self._time_range_row_widget.setVisible(bool(state))
            )
            self.viewLayout.addWidget(time_card)

        # Bundle options card
        bundle_card = SimpleCardWidget()
        bundle_card.setBorderRadius(8)
        bundle_layout = QVBoxLayout(bundle_card)
        bundle_layout.setContentsMargins(20, 16, 20, 16)
        bundle_layout.setSpacing(8)
        bundle_layout.addWidget(StrongBodyLabel("打包选项"))
        self._cb_annotations = CheckBox("包含标注（markers + segments）")
        self._cb_annotations.setChecked(True)
        self._cb_metadata = CheckBox("包含 recording 元数据")
        self._cb_metadata.setChecked(True)
        for cb in (self._cb_annotations, self._cb_metadata):
            bundle_layout.addWidget(cb)
        self.viewLayout.addWidget(bundle_card)

        # Output directory card
        output_card = SimpleCardWidget()
        output_card.setBorderRadius(8)
        output_layout = QVBoxLayout(output_card)
        output_layout.setContentsMargins(20, 16, 20, 16)
        output_layout.setSpacing(8)
        output_layout.addWidget(StrongBodyLabel("输出目录"))
        output_row = QHBoxLayout()
        output_row.setSpacing(8)
        self._output_dir_edit = LineEdit()
        self._output_dir_edit.setReadOnly(True)
        self._output_dir_edit.setPlaceholderText("尚未选择输出目录")
        choose_btn = PushButton("选择目录")
        choose_btn.clicked.connect(self._on_choose_output_dir)
        output_row.addWidget(self._output_dir_edit, 1)
        output_row.addWidget(choose_btn, 0, Qt.AlignmentFlag.AlignRight)
        output_layout.addLayout(output_row)
        self.viewLayout.addWidget(output_card)

    def build_request(self) -> ExportRequest | None:
        """Collect form state into ExportRequest. Returns None if invalid."""
        selections: list[StreamSelection] = []
        for desc, cb, combo in self._stream_rows:
            if not cb.isChecked():
                continue
            fmt_id = combo.currentData()
            if not isinstance(fmt_id, str):
                continue
            selections.append(StreamSelection(stream_id=desc.stream_id, format_id=fmt_id))

        if not selections:
            return None

        time_range_ns: tuple[int, int] | None = None
        if len(self._recording_ids) == 1 and self._time_range_enabled.isChecked():
            start = _parse_hms_to_ns(self._time_start_edit.text())
            end = _parse_hms_to_ns(self._time_end_edit.text())
            if start is None or end is None or start >= end:
                return None
            time_range_ns = (start, end)

        if len(self._recording_ids) == 1:
            mode = ExportMode.TIMESLICE if time_range_ns else ExportMode.SINGLE
        else:
            mode = ExportMode.MULTI

        return ExportRequest(
            mode=mode,
            recording_ids=tuple(self._recording_ids),
            streams=tuple(selections),
            time_range_ns=time_range_ns,
            include_annotations=self._cb_annotations.isChecked(),
            include_recording_metadata=self._cb_metadata.isChecked(),
        )

    def validate(self) -> bool:
        """Called by MessageBoxBase when yesButton clicked. Prevents close if invalid."""
        return self.build_request() is not None

    def selected_output_dir(self) -> str | None:
        """Returns the chosen output directory path."""
        return self._output_dir

    def _on_choose_output_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "选择导出输出目录", self._output_dir or ""
        )
        if selected:
            self._output_dir = selected
            self._output_dir_edit.setText(selected)


__all__ = ["ExportDialog"]
