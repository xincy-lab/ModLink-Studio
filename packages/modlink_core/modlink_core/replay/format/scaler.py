from __future__ import annotations

import numpy as np

from ..reader import RecordingReader


class GlobalMinMaxScaler:
    """Computes and caches global min/max for a stream across all frames.

    Uses RecordingReader.stream_value_range() which already has its own cache.
    This class is a thin wrapper that provides a normalize() convenience method.
    """

    def __init__(self, reader: RecordingReader) -> None:
        self._reader = reader

    def get_range(self, stream_id: str) -> tuple[float, float] | None:
        """Return (min, max) for stream_id, or None if stream has no frames."""
        return self._reader.stream_value_range(stream_id)

    def normalize(self, data: np.ndarray, stream_id: str) -> np.ndarray:
        """Normalize data to [0.0, 1.0] using global min/max.

        Returns float32 array same shape as input.
        If vmin == vmax (constant data), returns zeros.
        Raises ValueError if stream has no frames.
        """
        result = self.get_range(stream_id)
        if result is None:
            raise ValueError(f"stream {stream_id!r} has no frames — cannot normalize")
        vmin, vmax = result
        if vmax == vmin:
            return np.zeros_like(data, dtype=np.float32)
        return ((data - vmin) / (vmax - vmin)).astype(np.float32)
