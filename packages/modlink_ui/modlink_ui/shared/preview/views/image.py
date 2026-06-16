from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QVBoxLayout
from qfluentwidgets import isDarkTheme, qconfig

from modlink_sdk import FrameEnvelope, StreamDescriptor
from modlink_ui.bridge import QtSettingsBridge

from .base import BaseStreamView


class ImageStreamView(BaseStreamView):
    def __init__(
        self,
        descriptor: StreamDescriptor,
        settings: QtSettingsBridge,
        parent=None,
    ) -> None:
        super().__init__(descriptor, settings, parent=parent)
        self._latest_image: np.ndarray | None = None
        self._transform_mode = "none"
        self._colormap = "gray"
        self._value_range_mode = "auto"
        self._manual_min = 0.0
        self._manual_max = 1.0
        self._interpolation = "nearest"

        self._graphics_widget = pg.GraphicsLayoutWidget(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._graphics_widget, 1)

        self._last_shape: tuple[int, ...] | None = None
        self._view_box = self._graphics_widget.addViewBox()
        self._view_box.setAspectLocked(True)
        self._view_box.setMenuEnabled(False)
        self._view_box.setMouseEnabled(x=False, y=False)
        self._view_box.invertY(True)
        self._image_item = pg.ImageItem(axisOrder="row-major")
        self._view_box.addItem(self._image_item)
        self._apply_interpolation_mode()
        qconfig.themeChangedFinished.connect(self._apply_theme)
        self._apply_theme()

        self.setMinimumHeight(280)

    def _ingest_frame(self, frame: FrameEnvelope) -> bool:
        data = np.asarray(frame.data)
        image = self._extract_image(data)
        if image is None:
            return False
        self._latest_image = image
        return True

    def clear(self) -> None:
        super().clear()
        self._latest_image = None
        self._image_item.clear()
        self._last_shape = None

    def _render(self) -> None:
        if self._latest_image is None:
            return

        image = self._apply_transform(self._latest_image)
        auto_range = image.shape != self._last_shape
        self._last_shape = image.shape
        levels = self._resolve_levels(image)
        self._image_item.setLookupTable(self._build_lookup_table(image))
        self._image_item.setImage(
            image,
            autoLevels=levels is None,
            levels=levels,
        )
        if auto_range and self._view_box is not None:
            self._view_box.autoRange(padding=0.0)

    def _extract_image(self, data: np.ndarray) -> np.ndarray | None:
        if data.ndim != 4 or data.shape[1] <= 0:
            return None
        latest = np.asarray(data[:, -1, :, :])
        return self._normalize_image(self._compose_image(latest))

    def _compose_image(self, latest: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def _normalize_image(self, image: np.ndarray) -> np.ndarray:
        normalized = np.asarray(image)
        if normalized.ndim not in {2, 3}:
            return normalized
        if np.issubdtype(normalized.dtype, np.integer):
            return normalized
        return np.asarray(normalized, dtype=np.float32)

    def _apply_interpolation_mode(self) -> None:
        self._image_item.setAutoDownsample(self._interpolation != "nearest")

    def _apply_theme(self) -> None:
        self._graphics_widget.setBackground("#2B2B2B" if isDarkTheme() else "#FFFFFF")

    def _resolve_levels(self, image: np.ndarray) -> tuple[float, float] | None:
        if image.ndim != 2:
            return None
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

    def _build_lookup_table(self, image: np.ndarray) -> np.ndarray | None:
        if image.ndim != 2:
            return None
        if self._colormap == "gray":
            return None

        name_map = {
            "viridis": "viridis",
            "plasma": "plasma",
            "inferno": "inferno",
            "magma": "magma",
            "turbo": "turbo",
        }
        cmap_name = name_map.get(self._colormap)
        if cmap_name is None:
            return None
        try:
            color_map = pg.colormap.get(cmap_name)
        except Exception:
            return None
        return color_map.getLookupTable(alpha=False)

    def _apply_transform(self, image: np.ndarray) -> np.ndarray:
        transformed = np.asarray(image)
        if self._transform_mode == "flip_horizontal":
            return np.fliplr(transformed)
        if self._transform_mode == "flip_vertical":
            return np.flipud(transformed)
        if self._transform_mode == "rotate_90":
            return np.rot90(transformed, k=1)
        if self._transform_mode == "rotate_180":
            return np.rot90(transformed, k=2)
        if self._transform_mode == "rotate_270":
            return np.rot90(transformed, k=3)
        return transformed
