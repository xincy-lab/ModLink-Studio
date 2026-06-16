from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from modlink_core.replay.format.raster_png_segmented import (
    write_raster_waterfall_segmented_zip,
)


def _make_reader(
    *,
    n_channels: int = 2,
    chunk_t: int = 4,
    line_length: int = 8,
    n_chunks: int = 25,
    stream_id: str = "raster",
    stream_key: str = "raster",
    channel_names: tuple[str, ...] | None = None,
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

    frames = []
    refs = []
    for chunk_idx in range(n_chunks):
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

    all_data = np.concatenate([f.data for f in frames])
    reader.stream_value_range.return_value = (float(all_data.min()), float(all_data.max()))

    return reader, tuple(refs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_segment_count(tmp_path: Path) -> None:
    """25 chunks, segment_chunks=10 → 3 segments per channel (ceil(25/10)=3)."""
    reader, refs = _make_reader(n_channels=2, n_chunks=25)
    out = tmp_path / "out.zip"
    write_raster_waterfall_segmented_zip(reader, "raster", refs, 10, out)

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()

    # 3 segments × 2 channels = 6 PNGs
    pngs = [n for n in names if n.endswith(".png")]
    assert len(pngs) == 6

    # Verify segment indices present: seg0001, seg0002, seg0003
    seg_indices = {n.split("_seg")[1].replace(".png", "") for n in pngs}
    assert seg_indices == {"0001", "0002", "0003"}


def test_last_segment_smaller(tmp_path: Path) -> None:
    """25 chunks, segment_chunks=10 → last segment has 5 chunks (T=5*chunk_t)."""
    chunk_t = 4
    reader, refs = _make_reader(n_channels=1, chunk_t=chunk_t, n_chunks=25)
    out = tmp_path / "out.zip"
    write_raster_waterfall_segmented_zip(reader, "raster", refs, 10, out)

    with zipfile.ZipFile(out) as zf:
        # Last segment for ch01 is seg0003
        last_png_bytes = zf.read("raster_ch01_seg0003.png")

    import io

    from PIL import Image

    img = Image.open(io.BytesIO(last_png_bytes))
    width, height = img.size
    # Last segment: 5 chunks × 4 time steps = 20 rows
    assert height == 5 * chunk_t


def test_zip_contains_meta(tmp_path: Path) -> None:
    """ZIP always contains meta.json with required keys."""
    reader, refs = _make_reader(n_channels=2, n_chunks=25)
    out = tmp_path / "out.zip"
    write_raster_waterfall_segmented_zip(reader, "raster", refs, 10, out)

    with zipfile.ZipFile(out) as zf:
        assert "meta.json" in zf.namelist()
        meta = json.loads(zf.read("meta.json"))

    assert "channel_names" in meta
    assert "segment_chunks" in meta
    assert "total_segments" in meta
    assert "value_range" in meta
    assert "shape" in meta
    assert meta["segment_chunks"] == 10
    assert meta["total_segments"] == 3
    assert len(meta["shape"]) == 3  # [C, T_total, L]


def test_png_naming(tmp_path: Path) -> None:
    """First PNG is {stream_key}_ch01_seg0001.png."""
    reader, refs = _make_reader(n_channels=1, n_chunks=5, stream_key="spectrogram")
    out = tmp_path / "out.zip"
    write_raster_waterfall_segmented_zip(reader, "raster", refs, 10, out)

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()

    assert "spectrogram_ch01_seg0001.png" in names


def test_empty_frame_refs(tmp_path: Path) -> None:
    """Empty tuple → ZIP with only meta.json."""
    descriptor = MagicMock()
    descriptor.stream_key = "raster"
    descriptor.channel_names = ("ch1", "ch2")

    reader = MagicMock()
    reader.descriptors.return_value = {"raster": descriptor}

    out = tmp_path / "out.zip"
    write_raster_waterfall_segmented_zip(reader, "raster", (), 10, out)

    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()

    assert names == ["meta.json"]
    reader.load_frame.assert_not_called()
