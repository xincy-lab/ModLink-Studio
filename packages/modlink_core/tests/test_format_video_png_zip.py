from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from PIL import Image

from modlink_core.replay.format.video_png_zip import write_video_png_zip
from modlink_core.replay.reader import RecordedFrameRef
from modlink_sdk import FrameEnvelope, StreamDescriptor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_descriptor(
    *,
    channel_count: int = 3,
    sample_rate_hz: float = 30.0,
    chunk_size: int = 2,
) -> StreamDescriptor:
    return StreamDescriptor(
        device_id="test.01",
        stream_key="cam",
        payload_type="video",
        nominal_sample_rate_hz=sample_rate_hz,
        chunk_size=chunk_size,
        channel_names=(),
        display_name="Test Camera",
        metadata={},
    )


def _make_ref(timestamp_ns: int, frame_index: int = 0) -> RecordedFrameRef:
    return RecordedFrameRef(
        stream_id="cam",
        frame_index=frame_index,
        timestamp_ns=timestamp_ns,
        seq=frame_index,
        file_name="frames.bin",
        relative_timestamp_ns=0,
    )


def _make_reader(
    descriptor: StreamDescriptor,
    frames: list[tuple[RecordedFrameRef, np.ndarray]],
) -> MagicMock:
    reader = MagicMock()
    reader.descriptors.return_value = {"cam": descriptor}

    envelope_map = {ref: data for ref, data in frames}

    def load_frame(ref: RecordedFrameRef) -> FrameEnvelope:
        data = envelope_map[ref]
        return FrameEnvelope(
            device_id=descriptor.device_id,
            stream_key=descriptor.stream_key,
            timestamp_ns=ref.timestamp_ns,
            data=data,
            seq=ref.seq,
        )

    reader.load_frame.side_effect = load_frame
    return reader


def _make_video_data(
    channel_count: int,
    chunk_size: int,
    height: int = 4,
    width: int = 6,
) -> np.ndarray:
    """Return (C, T, H, W) uint8 array with sequential values mod 256."""
    size = channel_count * chunk_size * height * width
    return np.arange(size, dtype=np.uint8).reshape(channel_count, chunk_size, height, width)


def _build_5chunk_reader(
    channel_count: int = 3, chunk_size: int = 2
) -> tuple[MagicMock, tuple[RecordedFrameRef, ...]]:
    descriptor = _make_descriptor(channel_count=channel_count, chunk_size=chunk_size)
    refs = tuple(_make_ref(timestamp_ns=i * 100_000_000, frame_index=i) for i in range(5))
    frames = [(ref, _make_video_data(channel_count, chunk_size)) for ref in refs]
    reader = _make_reader(descriptor, frames)
    return reader, refs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_frame_count(tmp_path: Path) -> None:
    """5 chunks × chunk_size=2 → 10 PNG files in ZIP."""
    reader, refs = _build_5chunk_reader()
    out = tmp_path / "video.zip"
    write_video_png_zip(reader, "cam", refs, out)

    with zipfile.ZipFile(out) as zf:
        png_names = [n for n in zf.namelist() if n.endswith(".png")]
    assert len(png_names) == 10


def test_index_csv_exists(tmp_path: Path) -> None:
    """ZIP must contain index.csv."""
    reader, refs = _build_5chunk_reader()
    out = tmp_path / "video.zip"
    write_video_png_zip(reader, "cam", refs, out)

    with zipfile.ZipFile(out) as zf:
        assert "index.csv" in zf.namelist()


def test_index_csv_row_count(tmp_path: Path) -> None:
    """10 frames → index.csv has 10 data rows (plus 1 header)."""
    reader, refs = _build_5chunk_reader()
    out = tmp_path / "video.zip"
    write_video_png_zip(reader, "cam", refs, out)

    with zipfile.ZipFile(out) as zf:
        csv_text = zf.read("index.csv").decode("utf-8")

    lines = [ln for ln in csv_text.splitlines() if ln.strip()]
    assert lines[0] == "frame_index,timestamp_ns,file_in_zip"
    assert len(lines) == 11  # 1 header + 10 data rows


def test_rgb_mode(tmp_path: Path) -> None:
    """3-channel video → PNG mode is 'RGB'."""
    reader, refs = _build_5chunk_reader(channel_count=3)
    out = tmp_path / "video.zip"
    write_video_png_zip(reader, "cam", refs, out)

    with zipfile.ZipFile(out) as zf:
        png_bytes = zf.read("frame_000000.png")

    img = Image.open(io.BytesIO(png_bytes))
    assert img.mode == "RGB"


def test_grayscale_mode(tmp_path: Path) -> None:
    """1-channel video → PNG mode is 'L'."""
    reader, refs = _build_5chunk_reader(channel_count=1)
    out = tmp_path / "video.zip"
    write_video_png_zip(reader, "cam", refs, out)

    with zipfile.ZipFile(out) as zf:
        png_bytes = zf.read("frame_000000.png")

    img = Image.open(io.BytesIO(png_bytes))
    assert img.mode == "L"


def test_invalid_channels_raises(tmp_path: Path) -> None:
    """2-channel video → ValueError."""
    reader, refs = _build_5chunk_reader(channel_count=2)
    out = tmp_path / "video.zip"

    with pytest.raises(ValueError, match="unsupported channel count"):
        write_video_png_zip(reader, "cam", refs, out)
