"""Tests for the viridis colormap LUT module."""

import numpy as np

from modlink_core.replay.format.colormap import _VIRIDIS_LUT, apply_viridis


def test_lut_shape() -> None:
    assert _VIRIDIS_LUT.shape == (256, 3)
    assert _VIRIDIS_LUT.dtype == np.uint8


def test_apply_viridis_output_shape() -> None:
    data = np.zeros((4, 8), dtype=np.float32)
    result = apply_viridis(data, vmin=0.0, vmax=1.0)
    assert result.shape == (4, 8, 3)


def test_apply_viridis_min_maps_to_0() -> None:
    data = np.array([[0.0]])
    result = apply_viridis(data, vmin=0.0, vmax=1.0)
    np.testing.assert_array_equal(result[0, 0], _VIRIDIS_LUT[0])


def test_apply_viridis_max_maps_to_255() -> None:
    data = np.array([[1.0]])
    result = apply_viridis(data, vmin=0.0, vmax=1.0)
    np.testing.assert_array_equal(result[0, 0], _VIRIDIS_LUT[255])


def test_apply_viridis_constant_data() -> None:
    # vmin == vmax must not raise ZeroDivisionError; all pixels get index 0
    data = np.full((3, 3), 5.0)
    result = apply_viridis(data, vmin=5.0, vmax=5.0)
    assert result.shape == (3, 3, 3)
    for row in result:
        for pixel in row:
            np.testing.assert_array_equal(pixel, _VIRIDIS_LUT[0])
