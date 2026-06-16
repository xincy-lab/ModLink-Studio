from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget

from modlink_sdk import FrameEnvelope, StreamDescriptor
from modlink_ui.bridge import QtSettingsBridge
from modlink_ui.shared.ui_settings.preview_refresh_rate import (
    UI_PREVIEW_REFRESH_RATE_HZ_KEY,
    declare_preview_refresh_rate_settings,
    normalize_preview_refresh_rate_hz,
)


class BaseStreamView(QWidget):
    def __init__(
        self,
        descriptor: StreamDescriptor,
        settings: QtSettingsBridge,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self.descriptor = descriptor
        self._settings = settings
        declare_preview_refresh_rate_settings(self._settings)
        if self._settings.path is not None and self._settings.path.exists():
            self._settings.load(ignore_unknown=True)
        self._dirty = False
        self._has_frame = False

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._flush)
        self._apply_refresh_rate(self._load_refresh_rate_hz())
        self._settings.sig_setting_changed.connect(self._on_setting_changed)

    def push_frame(self, frame: FrameEnvelope) -> None:
        if not self._ingest_frame(frame):
            return
        self._has_frame = True
        self._dirty = True

    def clear(self) -> None:
        """Clear all buffered data and reset the view to its initial state."""
        self._has_frame = False
        self._dirty = False

    @property
    def has_frame(self) -> bool:
        return self._has_frame

    def _ingest_frame(self, frame: FrameEnvelope) -> bool:
        raise NotImplementedError

    def _render(self) -> None:
        raise NotImplementedError

    def _flush(self) -> None:
        if not self._dirty:
            return
        self._dirty = False
        self._render()

    def _on_setting_changed(self, event: object) -> None:
        if getattr(event, "key", None) != UI_PREVIEW_REFRESH_RATE_HZ_KEY:
            return
        self._apply_refresh_rate(self._load_refresh_rate_hz())

    def _load_refresh_rate_hz(self) -> int:
        return normalize_preview_refresh_rate_hz(self._settings.ui.preview.refresh_rate_hz.value)

    def _apply_refresh_rate(self, refresh_rate_hz: int) -> None:
        interval_ms = max(16, int(round(1000 / max(1, int(refresh_rate_hz)))))
        self._refresh_timer.start(interval_ms)
