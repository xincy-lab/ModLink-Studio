from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
from PIL import Image

from modlink_core.replay.format.raster_png import write_raster_waterfall_png


def _make_reader(
    *,
    n_channels: int = 2,
    chunk_t: int = 4,
    line_length: int = 8,
    n_chunks: int = 3,
    stream_id: str = "raster",
    stream_key: str = "raster",
    channel_names: tuple[str, ...] | None = None,
    constant_value: float | None = None,
) -> tuple[MagicMock, tuple]:
    """Build a mock RecordingReader and matching frame_refs tuple."""
    resolved_names = (
        channel_names
        if channel_names is not None
        else tuple(f"ch{i + 1}" for i in range(n_channels))
    )

    descriptor = MagicMock()
    descriptor.stream_key = stream_key
    descriptor.channel_names = resolved_names

    reader = MagicMock()
    reader.descriptors.return_value = {stream_id: descriptor}

    # Build frame data: shape (C, T, L)
    frames = []
    refs = []
    for chunk_idx in range(n_chunks):
        if constant_value is not None:
            data = np.full((n_channels, chunk_t, line_length), constant_value, dtype=np.float32)
        else:
            size = n_channels * chunk_t * line_length
            data = np.arange(chunk_idx * size, chunk_idx * size + size, dtype=np.float32).reshape(
                n_channels, chunk_t, line_length
            )

        envelope = MagicMock()
        envelope.data = data
        envelope.timestamp_ns = 1_000_000_000 * (chunk_idx + 1)
        frames.append(envelope)

        ref = MagicMock()
        refs.append(ref)

    reader.load_frame.side_effect = frames

    # stream_value_range used by GlobalMinMaxScaler.get_range
    if constant_value is not None:
        reader.stream_value_range.return_value = (constant_value, constant_value)
    else:
        all_data = np.concatenate([f.data for f in frames])
        reader.stream_value_range.return_value = (float(all_data.min()), float(all_data.max()))

    return reader, tuple(refs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_one_png_per_channel(tmp_path: Path) -> None:
    """2-channel raster, 3 chunks → 2 PNG files in output_dir."""
    reader, refs = _make_reader(n_channels=2, n_chunks=3)
    write_raster_waterfall_png(reader, "raster", refs, tmp_path)

    pngs = sorted(tmp_path.glob("*.png"))
    assert len(pngs) == 2
    names = {p.name for p in pngs}
    assert "raster_ch1_waterfall.png" in names
    assert "raster_ch2_waterfall.png" in names


def test_png_dimensions(tmp_path: Path) -> None:
    """raster (T=4, L=8), 3 chunks → PNG size width=8, height=12."""
    reader, refs = _make_reader(n_channels=1, chunk_t=4, line_length=8, n_chunks=3)
    write_raster_waterfall_png(reader, "raster", refs, tmp_path)

    img = Image.open(tmp_path / "raster_ch1_waterfall.png")
    width, height = img.size
    assert width == 8
    assert height == 12  # 3 chunks × 4 time steps


def test_sidecar_json_exists(tmp_path: Path) -> None:
    """meta.json written alongside PNGs with expected keys."""
    reader, refs = _make_reader(n_channels=2, n_chunks=3, stream_key="eeg")
    write_raster_waterfall_png(reader, "raster", refs, tmp_path)

    meta_path = tmp_path / "eeg_waterfall.meta.json"
    assert meta_path.exists()

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert "channel_names" in meta
    assert "time_range_ns" in meta
    assert "value_range" in meta
    assert "shape" in meta
    assert len(meta["time_range_ns"]) == 2
    assert len(meta["value_range"]) == 2
    assert len(meta["shape"]) == 3  # [C, T_total, L]


def test_empty_frame_refs_no_output(tmp_path: Path) -> None:
    """Empty tuple → no files written."""
    reader = MagicMock()
    write_raster_waterfall_png(reader, "raster", (), tmp_path)

    assert list(tmp_path.iterdir()) == []
    reader.descriptors.assert_not_called()
    reader.load_frame.assert_not_called()


def test_constant_data_no_crash(tmp_path: Path) -> None:
    """All-same-value data (vmin==vmax) → no division by zero, PNG written."""
    reader, refs = _make_reader(n_channels=1, n_chunks=2, constant_value=5.0)
    # Should not raise
    write_raster_waterfall_png(reader, "raster", refs, tmp_path)

    pngs = list(tmp_path.glob("*.png"))
    assert len(pngs) == 1

    img = Image.open(pngs[0])
    arr = np.array(img)
    # All pixels should map to viridis index 0 = [68, 1, 84]
    assert arr.shape[2] == 3
    assert np.all(arr[:, :, 0] == 68)
    assert np.all(arr[:, :, 1] == 1)
    assert np.all(arr[:, :, 2] == 84)
