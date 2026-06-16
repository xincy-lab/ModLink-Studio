from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from modlink_core.replay.format.scaler import GlobalMinMaxScaler


def _make_scaler(range_return: tuple[float, float] | None) -> GlobalMinMaxScaler:
    reader = MagicMock()
    reader.stream_value_range.return_value = range_return
    return GlobalMinMaxScaler(reader)


def test_normalize_basic() -> None:
    scaler = _make_scaler((0.0, 10.0))
    data = np.array([0.0, 5.0, 10.0])
    result = scaler.normalize(data, "s1")
    np.testing.assert_allclose(result, [0.0, 0.5, 1.0])


def test_normalize_constant_data() -> None:
    scaler = _make_scaler((7.0, 7.0))
    data = np.array([7.0, 7.0, 7.0])
    result = scaler.normalize(data, "s1")
    np.testing.assert_array_equal(result, np.zeros(3, dtype=np.float32))


def test_normalize_no_frames_raises() -> None:
    scaler = _make_scaler(None)
    with pytest.raises(ValueError, match="no frames"):
        scaler.normalize(np.array([1.0, 2.0]), "empty_stream")


def test_get_range_delegates_to_reader() -> None:
    reader = MagicMock()
    reader.stream_value_range.return_value = (1.0, 5.0)
    scaler = GlobalMinMaxScaler(reader)
    result = scaler.get_range("my_stream")
    reader.stream_value_range.assert_called_once_with("my_stream")
    assert result == (1.0, 5.0)


def test_normalize_output_dtype() -> None:
    scaler = _make_scaler((0.0, 1.0))
    data = np.array([0.0, 0.5, 1.0], dtype=np.float64)
    result = scaler.normalize(data, "s1")
    assert result.dtype == np.float32
