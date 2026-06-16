from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QVBoxLayout
from qfluentwidgets import isDarkTheme, qconfig
from scipy import signal as sp_signal

from modlink_sdk import FrameEnvelope, StreamDescriptor
from modlink_ui.bridge import QtSettingsBridge

from ..settings.models import SignalFilterSettings, SignalPreviewSettings
from .base import BaseStreamView
from .signal_layout import (
    EMBEDDED_SIGNAL_PLOT_HEIGHT,
    compute_expanded_signal_ranges,
    compute_stacked_signal_range,
    resolve_signal_view_height,
)

DEFAULT_SIGNAL_WINDOW_SECONDS = 8


SIGNAL_WINDOW_SECONDS_OPTIONS = (1, 2, 4, 8, 12, 20)
LIGHT_SIGNAL_COLORS = (
    "#2D8CF0",
    "#19BE6B",
    "#FF9F43",
    "#E74C3C",
    "#8E44AD",
    "#16A085",
    "#34495E",
    "#D35400",
)
DARK_SIGNAL_COLORS = (
    "#4DA3FF",
    "#4CD37A",
    "#FFB74D",
    "#FF6B6B",
    "#C084FC",
    "#2DD4BF",
    "#CBD5E1",
    "#FB923C",
)


@dataclass(slots=True)
class _SignalFilterSpec:
    family: Literal["butterworth", "chebyshev1", "bessel"] = "butterworth"
    mode: Literal["none", "low_pass", "high_pass", "band_pass", "band_stop"] = "none"
    order: int = 4
    low_cutoff_hz: float = 1.0
    high_cutoff_hz: float = 40.0
    notch_enabled: bool = False
    notch_frequencies_hz: tuple[float, ...] = ()
    notch_q: float = 30.0
    chebyshev1_ripple_db: float = 1.0


@dataclass(slots=True)
class _SignalPlotBundle:
    plot_item: pg.PlotItem
    curves: list[object]
    channel_indices: tuple[int, ...]


class _SignalFilterPipeline:
    def __init__(self, sample_rate_hz: float) -> None:
        self.sample_rate_hz = max(1.0, float(sample_rate_hz))
        self._main_sos: np.ndarray | None = None
        self._notch_sos: list[np.ndarray] = []
        self._main_states: list[np.ndarray] = []
        self._notch_states: list[list[np.ndarray]] = []
        self._channel_count = 0

    def configure(self, spec: _SignalFilterSpec) -> None:
        self._main_sos = self._design_main_sos(spec)
        self._notch_sos = self._design_notch_sos(spec)
        self.reset_states()

    def reset_states(self) -> None:
        self._channel_count = 0
        self._main_states = []
        self._notch_states = []

    def process(self, data: np.ndarray) -> np.ndarray:
        if data.ndim != 2:
            return data
        channel_count = int(data.shape[0])
        if channel_count <= 0:
            return data
        self._ensure_channel_states(channel_count)

        output = np.empty_like(data, dtype=np.float32)
        for channel_index in range(channel_count):
            values = np.asarray(data[channel_index], dtype=np.float64)
            if self._main_sos is not None:
                values, self._main_states[channel_index] = sp_signal.sosfilt(
                    self._main_sos,
                    values,
                    zi=self._main_states[channel_index],
                )
            if self._notch_sos:
                notch_states = self._notch_states[channel_index]
                for notch_index, notch_sos in enumerate(self._notch_sos):
                    values, notch_states[notch_index] = sp_signal.sosfilt(
                        notch_sos,
                        values,
                        zi=notch_states[notch_index],
                    )
            output[channel_index] = values.astype(np.float32, copy=False)
        return output

    def _ensure_channel_states(self, channel_count: int) -> None:
        if channel_count == self._channel_count:
            return
        self._channel_count = channel_count

        main_sections = int(self._main_sos.shape[0]) if self._main_sos is not None else 0
        self._main_states = [
            np.zeros((main_sections, 2), dtype=np.float64) for _ in range(channel_count)
        ]

        self._notch_states = []
        for _ in range(channel_count):
            channel_states = [
                np.zeros((int(notch_sos.shape[0]), 2), dtype=np.float64)
                for notch_sos in self._notch_sos
            ]
            self._notch_states.append(channel_states)

    def _design_main_sos(self, spec: _SignalFilterSpec) -> np.ndarray | None:
        if spec.mode == "none":
            return None

        nyquist = self.sample_rate_hz * 0.5
        if nyquist <= 0:
            return None

        btype_map = {
            "low_pass": "lowpass",
            "high_pass": "highpass",
            "band_pass": "bandpass",
            "band_stop": "bandstop",
        }
        btype = btype_map.get(spec.mode)
        if btype is None:
            return None

        low = max(1e-6, min(float(spec.low_cutoff_hz), nyquist - 1e-6))
        high = max(1e-6, min(float(spec.high_cutoff_hz), nyquist - 1e-6))
        if spec.mode in {"band_pass", "band_stop"}:
            if low >= high:
                return None
            wn: float | tuple[float, float] = (low, high)
        else:
            wn = low

        try:
            if spec.family == "butterworth":
                return sp_signal.butter(
                    N=int(spec.order),
                    Wn=wn,
                    btype=btype,
                    fs=self.sample_rate_hz,
                    output="sos",
                )
            if spec.family == "chebyshev1":
                return sp_signal.cheby1(
                    N=int(spec.order),
                    rp=max(0.01, float(spec.chebyshev1_ripple_db)),
                    Wn=wn,
                    btype=btype,
                    fs=self.sample_rate_hz,
                    output="sos",
                )
            if spec.family == "bessel":
                return sp_signal.bessel(
                    N=int(spec.order),
                    Wn=wn,
                    btype=btype,
                    fs=self.sample_rate_hz,
                    output="sos",
                    norm="phase",
                )
        except ValueError:
            return None
        return None

    def _design_notch_sos(self, spec: _SignalFilterSpec) -> list[np.ndarray]:
        if not spec.notch_enabled:
            return []
        nyquist = self.sample_rate_hz * 0.5
        if nyquist <= 0:
            return []

        result: list[np.ndarray] = []
        for frequency in spec.notch_frequencies_hz:
            hz = float(frequency)
            if hz <= 0.0 or hz >= nyquist:
                continue
            normalized = hz / nyquist
            if normalized <= 0.0 or normalized >= 1.0:
                continue
            try:
                b, a = sp_signal.iirnotch(normalized, max(0.1, float(spec.notch_q)))
                result.append(sp_signal.tf2sos(b, a))
            except ValueError:
                continue
        return result


class _NonInteractiveViewBox(pg.ViewBox):
    def wheelEvent(self, event) -> None:
        event.ignore()


class _NonInteractiveAxisItem(pg.AxisItem):
    def wheelEvent(self, event) -> None:
        event.ignore()


class _SignalRingBuffer:
    def __init__(self, channels: int, max_samples: int):
        self.channels = channels
        self.max_samples = max_samples
        self.data = np.zeros((channels, max_samples), dtype=np.float32)
        self.ptr = 0
        self.full = False

    def extend(self, new_data: np.ndarray):
        chunk_size = new_data.shape[1]
        if chunk_size == 0:
            return

        if chunk_size >= self.max_samples:
            self.data[:, :] = new_data[:, -self.max_samples :]
            self.ptr = 0
            self.full = True
            return

        end = self.ptr + chunk_size
        if end <= self.max_samples:
            self.data[:, self.ptr : end] = new_data
            self.ptr = end
            if self.ptr == self.max_samples:
                self.ptr = 0
                self.full = True
        else:
            overflow = end - self.max_samples
            self.data[:, self.ptr :] = new_data[:, : self.max_samples - self.ptr]
            self.data[:, :overflow] = new_data[:, self.max_samples - self.ptr :]
            self.ptr = overflow
            self.full = True

    def get_linear(self) -> np.ndarray:
        if not self.full:
            return self.data[:, : self.ptr]
        return np.concatenate(
            (self.data[:, self.ptr :], self.data[:, : self.ptr]),
            axis=1,
        )

    def clear(self):
        self.ptr = 0
        self.full = False

    def resize(self, new_max_samples: int):
        new_data = np.zeros((self.channels, new_max_samples), dtype=np.float32)
        old_linear = self.get_linear()
        valid_len = old_linear.shape[1]

        if valid_len > new_max_samples:
            new_data[:, :] = old_linear[:, -new_max_samples:]
            self.ptr = 0
            self.full = True
        else:
            new_data[:, :valid_len] = old_linear
            self.ptr = valid_len % new_max_samples
            self.full = valid_len == new_max_samples

        self.data = new_data
        self.max_samples = new_max_samples


class SignalStreamView(BaseStreamView):
    def __init__(
        self,
        descriptor: StreamDescriptor,
        settings: QtSettingsBridge,
        parent=None,
    ) -> None:
        super().__init__(descriptor, settings, parent=parent)

        self._sample_rate_hz = max(1.0, float(descriptor.nominal_sample_rate_hz or 1.0))
        self._window_seconds = DEFAULT_SIGNAL_WINDOW_SECONDS
        self._max_samples = self._compute_max_samples(self._window_seconds)
        self._channel_names = tuple(descriptor.channel_names)
        self._ring_buffer: _SignalRingBuffer | None = None
        self._plot_bundles: list[_SignalPlotBundle] = []
        self._antialias_enabled = False
        self._auto_downsample_enabled = True
        self._layout_mode = "expanded"
        self._visible_channel_indices: tuple[int, ...] = ()
        self._y_range_mode = "auto"
        self._manual_y_min = -1.0
        self._manual_y_max = 1.0
        self._embedded_mode = True
        self._plot_signature: tuple[int, str, tuple[int, ...]] | None = None
        self._plot_height = EMBEDDED_SIGNAL_PLOT_HEIGHT
        self._filter_spec = _SignalFilterSpec()
        self._pipeline = _SignalFilterPipeline(sample_rate_hz=self._sample_rate_hz)
        self._pipeline.configure(self._filter_spec)
        self._colors = self._theme_signal_colors()

        self._graphics_widget = pg.GraphicsLayoutWidget(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._graphics_widget, 1)

        qconfig.themeChangedFinished.connect(self._apply_theme)
        self._apply_theme()
        self._refresh_view_geometry()

    @property
    def window_seconds(self) -> int:
        return self._window_seconds

    def apply_preview_settings(self, settings: SignalPreviewSettings) -> None:
        if not isinstance(settings, SignalPreviewSettings):
            raise TypeError("signal preview view requires SignalPreviewSettings")

        self._apply_window_seconds(settings.window_seconds)
        self._antialias_enabled = bool(settings.antialias_enabled)
        self._layout_mode = settings.layout_mode
        self._visible_channel_indices = settings.visible_channel_indices
        self._y_range_mode = settings.y_range_mode
        self._manual_y_min = float(settings.manual_y_min)
        self._manual_y_max = float(settings.manual_y_max)

        self._auto_downsample_enabled = True
        self._plot_signature = None
        self._apply_render_quality()
        self._refresh_view_geometry()

        if self._ring_buffer is not None:
            self._ensure_plot_layout(self._ring_buffer.channels)

        next_spec = self._extract_filter_spec(settings.filter)
        if next_spec != self._filter_spec:
            self._filter_spec = next_spec
            self._pipeline.configure(self._filter_spec)
            self._reset_signal_state()
        elif self.has_frame:
            self._dirty = True

    def set_embedded_mode(self, embedded: bool) -> None:
        if self._embedded_mode == bool(embedded):
            return
        self._embedded_mode = bool(embedded)
        self._refresh_view_geometry()

    def sizeHint(self) -> QSize:
        return QSize(640, self._preferred_height())

    def minimumSizeHint(self) -> QSize:
        minimum_height = self._preferred_height() if self._embedded_mode else self._plot_height
        return QSize(320, minimum_height)

    def _compute_max_samples(self, window_seconds: int) -> int:
        return max(
            int(self._sample_rate_hz * window_seconds),
            int(self.descriptor.chunk_size) * 24,
            512,
        )

    def _apply_window_seconds(self, window_seconds: int) -> None:
        if window_seconds not in SIGNAL_WINDOW_SECONDS_OPTIONS:
            window_seconds = DEFAULT_SIGNAL_WINDOW_SECONDS
        self._window_seconds = window_seconds
        max_samples = self._compute_max_samples(window_seconds)
        if max_samples == self._max_samples:
            return

        self._max_samples = max_samples
        if self._ring_buffer is not None:
            self._ring_buffer.resize(self._max_samples)

        if self.has_frame:
            self._dirty = True

    def _apply_render_quality(self) -> None:
        for plot_bundle in self._plot_bundles:
            plot_bundle.plot_item.setDownsampling(
                ds=1,
                auto=self._auto_downsample_enabled,
                mode="peak",
            )
            plot_bundle.plot_item.setClipToView(True)
            for curve in plot_bundle.curves:
                curve.opts["antialias"] = self._antialias_enabled
                curve.setDownsampling(
                    ds=1,
                    auto=self._auto_downsample_enabled,
                    method="peak",
                )
                curve.setClipToView(self._auto_downsample_enabled)
                curve.updateItems(styleUpdate=True)
        if self.has_frame:
            self._dirty = True

    def _ensure_channels(self, channel_count: int) -> None:
        if channel_count <= 0:
            return
        if self._ring_buffer is not None and self._ring_buffer.channels == channel_count:
            return

        self._ring_buffer = _SignalRingBuffer(channel_count, self._max_samples)
        self._channel_names = tuple(
            self._channel_names[index] if index < len(self._channel_names) else f"ch{index + 1}"
            for index in range(channel_count)
        )
        self._plot_signature = None

    def clear(self) -> None:
        super().clear()
        self._pipeline.reset_states()
        if self._ring_buffer is not None:
            self._ring_buffer.clear()
        # Clear all visible curves so old data disappears from the plot
        for plot_bundle in self._plot_bundles:
            for curve in plot_bundle.curves:
                curve.setData([], [])

    def _ingest_frame(self, frame: FrameEnvelope) -> bool:
        data = np.asarray(frame.data)
        if data.ndim != 2:
            return False

        channel_count, chunk_size = int(data.shape[0]), int(data.shape[1])
        if channel_count <= 0 or chunk_size <= 0:
            return False

        self._ensure_channels(channel_count)
        processed = self._pipeline.process(np.asarray(data, dtype=np.float32))

        if self._ring_buffer is not None:
            self._ring_buffer.extend(processed)

        return True

    def _render(self) -> None:
        if self._ring_buffer is None:
            return

        linear = self._ring_buffer.get_linear()
        if linear.size == 0:
            return

        sample_count = int(linear.shape[1])
        if sample_count <= 0:
            return

        visible_channel_indices = self._ensure_plot_layout(int(linear.shape[0]))
        if not visible_channel_indices:
            return

        time_axis = (
            np.arange(sample_count, dtype=np.float32) - float(sample_count - 1)
        ) / np.float32(self._sample_rate_hz)

        if self._layout_mode == "stacked":
            self._render_stacked(linear, time_axis, visible_channel_indices)
        else:
            self._render_expanded(linear, time_axis, visible_channel_indices)

    def _render_stacked(
        self,
        linear: np.ndarray,
        time_axis: np.ndarray,
        visible_channel_indices: tuple[int, ...],
    ) -> None:
        if not self._plot_bundles:
            return
        plot_bundle = self._plot_bundles[0]
        for curve, channel_index in zip(plot_bundle.curves, visible_channel_indices):
            curve.setData(time_axis, linear[channel_index])

        plot_bundle.plot_item.setXRange(float(time_axis[0]), 0.0, padding=0.0)
        lower, upper = self._resolve_stacked_y_range(linear, visible_channel_indices)
        plot_bundle.plot_item.setYRange(lower, upper, padding=0.0)

    def _render_expanded(
        self,
        linear: np.ndarray,
        time_axis: np.ndarray,
        visible_channel_indices: tuple[int, ...],
    ) -> None:
        if not self._plot_bundles:
            return

        channel_values = [linear[index] for index in visible_channel_indices]
        if self._y_range_mode == "manual":
            manual_range = self._manual_y_range()
            y_ranges = [manual_range for _ in channel_values]
        else:
            y_ranges = compute_expanded_signal_ranges(channel_values)

        for plot_bundle, channel_index, y_range in zip(
            self._plot_bundles,
            visible_channel_indices,
            y_ranges,
        ):
            plot_bundle.curves[0].setData(time_axis, linear[channel_index])
            plot_bundle.plot_item.setXRange(float(time_axis[0]), 0.0, padding=0.0)
            plot_bundle.plot_item.setYRange(y_range[0], y_range[1], padding=0.0)

    def _resolve_stacked_y_range(
        self,
        linear: np.ndarray,
        visible_channel_indices: tuple[int, ...],
    ) -> tuple[float, float]:
        if self._y_range_mode == "manual":
            return self._manual_y_range()
        stacked_values = np.asarray([linear[index] for index in visible_channel_indices])
        return compute_stacked_signal_range(stacked_values)

    def _manual_y_range(self) -> tuple[float, float]:
        return (
            float(min(self._manual_y_min, self._manual_y_max)),
            float(max(self._manual_y_min, self._manual_y_max)),
        )

    def _ensure_plot_layout(self, channel_count: int) -> tuple[int, ...]:
        visible_channel_indices = self._effective_visible_channel_indices(channel_count)
        signature = (channel_count, self._layout_mode, visible_channel_indices)
        if signature == self._plot_signature:
            return visible_channel_indices

        self._graphics_widget.clear()
        self._plot_bundles.clear()
        self._plot_signature = signature

        if channel_count <= 0 or not visible_channel_indices:
            self._refresh_view_geometry()
            return visible_channel_indices

        if self._layout_mode == "stacked":
            plot_item = self._create_plot_item(show_bottom_axis=True)
            curves: list[object] = []
            legend = plot_item.addLegend(offset=(8, 8))
            for channel_index in visible_channel_indices:
                curve = self._create_curve(plot_item, channel_index)
                curves.append(curve)
                legend.addItem(curve, self._channel_label(channel_index))
            self._plot_bundles.append(
                _SignalPlotBundle(
                    plot_item=plot_item,
                    curves=curves,
                    channel_indices=visible_channel_indices,
                )
            )
        else:
            first_plot: pg.PlotItem | None = None
            for row, channel_index in enumerate(visible_channel_indices):
                show_bottom_axis = row == len(visible_channel_indices) - 1
                plot_item = self._create_plot_item(show_bottom_axis=show_bottom_axis)
                plot_item.setTitle(
                    self._channel_label(channel_index),
                    color=self._theme_secondary_text_color(),
                    size="10pt",
                )
                if first_plot is None:
                    first_plot = plot_item
                else:
                    plot_item.setXLink(first_plot)
                curve = self._create_curve(plot_item, channel_index)
                self._plot_bundles.append(
                    _SignalPlotBundle(
                        plot_item=plot_item,
                        curves=[curve],
                        channel_indices=(channel_index,),
                    )
                )
                if row < len(visible_channel_indices) - 1:
                    self._graphics_widget.nextRow()

        self._apply_render_quality()
        self._refresh_view_geometry()
        return visible_channel_indices

    def _create_plot_item(self, show_bottom_axis: bool) -> pg.PlotItem:
        plot_item = self._graphics_widget.addPlot(
            viewBox=_NonInteractiveViewBox(),
            axisItems={
                "left": _NonInteractiveAxisItem("left"),
                "bottom": _NonInteractiveAxisItem("bottom"),
            },
        )
        plot_item.setMenuEnabled(False)
        plot_item.showGrid(x=True, y=True, alpha=0.16)
        plot_item.hideButtons()
        plot_item.setClipToView(True)
        plot_item.setDownsampling(
            ds=1,
            auto=self._auto_downsample_enabled,
            mode="peak",
        )

        view_box = plot_item.getViewBox()
        view_box.setMenuEnabled(False)
        view_box.setMouseEnabled(x=False, y=False)

        if show_bottom_axis:
            plot_item.showAxis("bottom")
            plot_item.setLabel("bottom", "时间", units="s")
        else:
            plot_item.hideAxis("bottom")
        return plot_item

    def _create_curve(self, plot_item: pg.PlotItem, channel_index: int) -> object:
        return plot_item.plot(
            pen=pg.mkPen(self._colors[channel_index % len(self._colors)], width=1.5),
            antialias=self._antialias_enabled,
            autoDownsample=self._auto_downsample_enabled,
            downsample=1,
            downsampleMethod="peak",
            clipToView=self._auto_downsample_enabled,
        )

    def _effective_visible_channel_indices(self, channel_count: int) -> tuple[int, ...]:
        if channel_count <= 0:
            return ()
        requested = tuple(
            index for index in self._visible_channel_indices if 0 <= index < channel_count
        )
        if requested:
            return requested
        return tuple(range(channel_count))

    def _channel_label(self, channel_index: int) -> str:
        if channel_index < len(self._channel_names):
            label = self._channel_names[channel_index]
            if label:
                return label
        return f"ch{channel_index + 1}"

    def _preferred_height(self) -> int:
        if not self._embedded_mode:
            return self._plot_height
        return resolve_signal_view_height(
            self._layout_mode,
            self._geometry_visible_channel_count(),
            self._plot_height,
        )

    def _geometry_visible_channel_count(self) -> int:
        channel_count = (
            self._ring_buffer.channels
            if self._ring_buffer is not None
            else max(1, len(self._channel_names))
        )
        return len(self._effective_visible_channel_indices(channel_count))

    def _refresh_view_geometry(self) -> None:
        if self._embedded_mode:
            height = self._preferred_height()
            self.setMinimumHeight(height)
            self.setMaximumHeight(height)
        else:
            self.setMinimumHeight(self._plot_height)
            self.setMaximumHeight(16777215)
        self.updateGeometry()

        parent = self.parentWidget()
        while parent is not None:
            layout = parent.layout()
            if layout is not None:
                layout.invalidate()
            parent.updateGeometry()
            parent = parent.parentWidget()

    def _apply_theme(self) -> None:
        self._colors = self._theme_signal_colors()
        self._graphics_widget.setBackground(self._theme_background_color())
        if self._ring_buffer is not None:
            self._plot_signature = None
            self._ensure_plot_layout(self._ring_buffer.channels)
        if self.has_frame:
            self._dirty = True

    def _reset_signal_state(self) -> None:
        self._pipeline.reset_states()
        if self._ring_buffer is not None:
            self._ring_buffer.clear()
        if self.has_frame:
            self._dirty = True

    def _extract_filter_spec(self, filter_settings: SignalFilterSettings) -> _SignalFilterSpec:
        nyquist = max(self._sample_rate_hz * 0.5, 1.0)
        mode = filter_settings.mode
        family = filter_settings.family
        order = max(1, min(12, int(filter_settings.order)))

        low_cutoff = float(filter_settings.low_cutoff_hz)
        high_cutoff = float(filter_settings.high_cutoff_hz)
        max_cutoff = max(0.001, nyquist - 1e-6)
        low_cutoff = max(0.001, min(low_cutoff, max_cutoff))
        high_cutoff = max(0.001, min(high_cutoff, max_cutoff))

        if low_cutoff > high_cutoff:
            low_cutoff, high_cutoff = high_cutoff, low_cutoff
        if mode in {"band_pass", "band_stop"} and low_cutoff >= high_cutoff:
            low_cutoff = max(0.001, min(low_cutoff, max_cutoff * 0.5))
            high_cutoff = min(max_cutoff, max(low_cutoff + 0.001, high_cutoff))

        notch_enabled = bool(filter_settings.notch_enabled)
        raw_frequencies = filter_settings.notch_frequencies_hz
        notch_frequencies: list[float] = []
        if isinstance(raw_frequencies, (list, tuple)):
            for value in raw_frequencies:
                try:
                    normalized = round(float(value), 6)
                except (TypeError, ValueError):
                    continue
                if 0.0 < normalized < nyquist:
                    notch_frequencies.append(normalized)
        notch_frequencies = sorted(set(notch_frequencies))

        notch_q = max(
            0.1,
            float(filter_settings.notch_q),
        )
        chebyshev1_ripple_db = max(
            0.01,
            float(filter_settings.chebyshev1_ripple_db),
        )

        return _SignalFilterSpec(
            family=family,
            mode=mode,
            order=order,
            low_cutoff_hz=low_cutoff,
            high_cutoff_hz=high_cutoff,
            notch_enabled=notch_enabled,
            notch_frequencies_hz=tuple(notch_frequencies),
            notch_q=notch_q,
            chebyshev1_ripple_db=chebyshev1_ripple_db,
        )

    @staticmethod
    def _theme_background_color() -> str:
        return "#2B2B2B" if isDarkTheme() else "#FFFFFF"

    @staticmethod
    def _theme_secondary_text_color() -> str:
        return "#D4D4D4" if isDarkTheme() else "#666666"

    @staticmethod
    def _theme_signal_colors() -> tuple[str, ...]:
        return DARK_SIGNAL_COLORS if isDarkTheme() else LIGHT_SIGNAL_COLORS
