from __future__ import annotations

from collections import deque

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QVBoxLayout
from qfluentwidgets import isDarkTheme, qconfig

from modlink_sdk import FrameEnvelope, StreamDescriptor
from modlink_ui.bridge import QtSettingsBridge

from ..settings.models import RasterPreviewSettings
from .base import BaseStreamView

DEFAULT_RASTER_WINDOW_SECONDS = 8
RASTER_WINDOW_SECONDS_OPTIONS = (1, 2, 4, 8, 12, 20)


class RasterStreamView(BaseStreamView):
    def __init__(
        self,
        descriptor: StreamDescriptor,
        settings: QtSettingsBridge,
        parent=None,
    ) -> None:
        super().__init__(descriptor, settings, parent=parent)
        self._sample_rate_hz = max(1.0, float(descriptor.nominal_sample_rate_hz or 1.0))
        self._window_seconds = DEFAULT_RASTER_WINDOW_SECONDS
        self._max_lines = self._compute_max_lines(self._window_seconds)
        self._line_buffer: deque[np.ndarray] = deque(maxlen=self._max_lines)
        self._line_length = 0

        self._transform_mode = "none"
        self._colormap = "gray"
        self._value_range_mode = "auto"
        self._manual_min = 0.0
        self._manual_max = 1.0
        self._interpolation = "nearest"

        self._graphics_widget = pg.GraphicsLayoutWidget(self)
        self._view_box = self._graphics_widget.addViewBox()
        self._view_box.setAspectLocked(False)
        self._view_box.setMenuEnabled(False)
        self._view_box.setMouseEnabled(x=False, y=False)
        self._view_box.invertY(True)
        self._image_item = pg.ImageItem(axisOrder="row-major")
        self._view_box.addItem(self._image_item)
        self._apply_interpolation_mode()
        self._last_shape: tuple[int, ...] | None = None
        qconfig.themeChangedFinished.connect(self._apply_theme)
        self._apply_theme()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._graphics_widget, 1)
        self.setMinimumHeight(280)

    def apply_preview_settings(self, settings: RasterPreviewSettings) -> None:
        if not isinstance(settings, RasterPreviewSettings):
            raise TypeError("raster preview view requires RasterPreviewSettings")

        self._apply_window_seconds(settings.window_seconds)
        self._transform_mode = settings.transform
        self._colormap = settings.colormap
        self._value_range_mode = settings.value_range_mode
        self._manual_min = float(settings.manual_min)
        self._manual_max = float(settings.manual_max)
        self._interpolation = settings.interpolation
        self._apply_interpolation_mode()

        if self.has_frame:
            self._dirty = True

    def _compute_max_lines(self, window_seconds: int) -> int:
        return max(int(self._sample_rate_hz * window_seconds), 128)

    def _apply_window_seconds(self, window_seconds: int) -> None:
        if window_seconds not in RASTER_WINDOW_SECONDS_OPTIONS:
            window_seconds = DEFAULT_RASTER_WINDOW_SECONDS
        self._window_seconds = window_seconds
        max_lines = self._compute_max_lines(window_seconds)
        if max_lines == self._max_lines:
            return

        self._max_lines = max_lines
        self._line_buffer = deque(list(self._line_buffer)[-max_lines:], maxlen=max_lines)
        if self.has_frame:
            self._dirty = True

    def _ingest_frame(self, frame: FrameEnvelope) -> bool:
        data = np.asarray(frame.data)
        if data.ndim != 3:
            return False
        channel_count, time_count, line_length = data.shape
        if channel_count <= 0 or time_count <= 0 or line_length <= 0:
            return False

        averaged = np.mean(np.asarray(data, dtype=np.float32), axis=0)
        for line in averaged:
            self._line_buffer.append(np.asarray(line, dtype=np.float32))
        self._line_length = int(line_length)
        return True

    def clear(self) -> None:
        super().clear()
        self._line_buffer.clear()
        self._line_length = 0
        self._image_item.clear()
        self._last_shape = None

    def _render(self) -> None:
        if not self._line_buffer or self._line_length <= 0:
            return

        image = np.vstack(self._line_buffer)
        image = self._apply_transform(image)
        levels = self._resolve_levels(image)
        self._image_item.setLookupTable(self._build_lookup_table())
        self._image_item.setImage(
            image,
            autoLevels=levels is None,
            levels=levels,
        )

        auto_range = image.shape != self._last_shape
        self._last_shape = image.shape
        if auto_range:
            self._view_box.autoRange(padding=0.0)

    def _resolve_levels(self, image: np.ndarray) -> tuple[float, float] | None:
        if self._value_range_mode == "zero_to_one":
            return (0.0, 1.0)
        if self._value_range_mode == "zero_to_255":
            return (0.0, 255.0)
        if self._value_range_mode == "manual":
            minimum = min(self._manual_min, self._manual_max)
            maximum = max(self._manual_min, self._manual_max)
            if maximum <= minimum:
                return None
            return (minimum, maximum)
        return None

    def _build_lookup_table(self) -> np.ndarray | None:
        if self._colormap == "gray":
            return None
        cmap_name = {
            "viridis": "viridis",
            "plasma": "plasma",
            "inferno": "inferno",
            "magma": "magma",
            "turbo": "turbo",
        }.get(self._colormap)
        if cmap_name is None:
            return None
        try:
            color_map = pg.colormap.get(cmap_name)
        except Exception:
            return None
        return color_map.getLookupTable(alpha=False)

    def _apply_transform(self, image: np.ndarray) -> np.ndarray:
        if self._transform_mode == "flip_horizontal":
            return np.fliplr(image)
        if self._transform_mode == "flip_vertical":
            return np.flipud(image)
        if self._transform_mode == "rotate_90":
            return np.rot90(image, k=1)
        if self._transform_mode == "rotate_180":
            return np.rot90(image, k=2)
        if self._transform_mode == "rotate_270":
            return np.rot90(image, k=3)
        return image

    def _apply_interpolation_mode(self) -> None:
        self._image_item.setAutoDownsample(self._interpolation != "nearest")

    def _apply_theme(self) -> None:
        self._graphics_widget.setBackground("#2B2B2B" if isDarkTheme() else "#FFFFFF")
