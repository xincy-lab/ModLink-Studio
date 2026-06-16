from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from modlink_core.replay.format.field_png_zip import write_field_png_zip


def _make_reader(
    *,
    n_channels: int = 2,
    chunk_t: int = 1,
    height: int = 4,
    width: int = 4,
    n_chunks: int = 5,
    stream_id: str = "field",
    constant_value: float | None = None,
) -> tuple[MagicMock, tuple]:
    """Build a mock RecordingReader and matching frame_refs tuple for field data."""
    reader = MagicMock()

    frames = []
    refs = []
    for chunk_idx in range(n_chunks):
        if constant_value is not None:
            data = np.full((n_channels, chunk_t, height, width), constant_value, dtype=np.float32)
        else:
            size = n_channels * chunk_t * height * width
            data = np.arange(chunk_idx * size, chunk_idx * size + size, dtype=np.float32).reshape(
                n_channels, chunk_t, height, width
            )

        envelope = MagicMock()
        envelope.data = data
        envelope.timestamp_ns = 1_000_000_000 * (chunk_idx + 1)
        frames.append(envelope)

        ref = MagicMock()
        refs.append(ref)

    reader.load_frame.side_effect = frames

    if constant_value is not None:
        reader.stream_value_range.return_value = (constant_value, constant_value)
    else:
        all_data = np.concatenate([f.data.ravel() for f in frames])
        reader.stream_value_range.return_value = (float(all_data.min()), float(all_data.max()))

    return reader, tuple(refs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_png_count(tmp_path: Path) -> None:
    """2-channel × 5 chunks × T=1 → 10 PNG files in ZIP."""
    reader, refs = _make_reader(n_channels=2, chunk_t=1, n_chunks=5)
    out = tmp_path / "out.zip"
    write_field_png_zip(reader, "field", refs, out)

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    pngs = [n for n in names if n.endswith(".png")]
    assert len(pngs) == 10


def test_index_csv_exists(tmp_path: Path) -> None:
    """ZIP contains index.csv."""
    reader, refs = _make_reader(n_channels=1, n_chunks=2)
    out = tmp_path / "out.zip"
    write_field_png_zip(reader, "field", refs, out)

    with zipfile.ZipFile(out) as zf:
        assert "index.csv" in zf.namelist()


def test_index_csv_columns(tmp_path: Path) -> None:
    """index.csv has columns frame_index,channel,timestamp_ns,file_in_zip."""
    reader, refs = _make_reader(n_channels=1, n_chunks=2)
    out = tmp_path / "out.zip"
    write_field_png_zip(reader, "field", refs, out)

    with zipfile.ZipFile(out) as zf:
        csv_text = zf.read("index.csv").decode("utf-8")

    header = csv_text.splitlines()[0]
    assert header == "frame_index,channel,timestamp_ns,file_in_zip"


def test_constant_data_no_crash(tmp_path: Path) -> None:
    """All-same-value data (vmin==vmax) → no division by zero, PNGs written."""
    reader, refs = _make_reader(n_channels=1, n_chunks=2, constant_value=3.14)
    out = tmp_path / "out.zip"
    # Should not raise
    write_field_png_zip(reader, "field", refs, out)

    with zipfile.ZipFile(out) as zf:
        pngs = [n for n in zf.namelist() if n.endswith(".png")]
    assert len(pngs) == 2  # 1 channel × 2 chunks × T=1


def test_empty_frame_refs(tmp_path: Path) -> None:
    """Empty tuple → ZIP with only index.csv (header only)."""
    reader = MagicMock()
    out = tmp_path / "out.zip"
    write_field_png_zip(reader, "field", (), out)

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert names == ["index.csv"]
        csv_text = zf.read("index.csv").decode("utf-8")

    header = csv_text.strip()
    assert header == "frame_index,channel,timestamp_ns,file_in_zip"
    reader.load_frame.assert_not_called()
