from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from modlink_core.replay.format.video_mp4 import write_video_mp4


def _make_reader(
    *,
    n_channels: int = 3,
    chunk_t: int = 2,
    height: int = 4,
    width: int = 4,
    n_chunks: int = 2,
    stream_id: str = "video",
    stream_key: str = "cam",
    fps: float = 30.0,
) -> tuple[MagicMock, tuple]:
    """Build a mock RecordingReader and frame_refs for video data."""
    reader = MagicMock()

    descriptor = MagicMock()
    descriptor.stream_key = stream_key
    descriptor.nominal_sample_rate_hz = fps
    reader.descriptors.return_value = {stream_id: descriptor}

    frames = []
    refs = []
    for chunk_idx in range(n_chunks):
        size = n_channels * chunk_t * height * width
        data = np.arange(chunk_idx * size, chunk_idx * size + size, dtype=np.uint8).reshape(
            n_channels, chunk_t, height, width
        )

        envelope = MagicMock()
        envelope.data = data
        envelope.timestamp_ns = 1_000_000_000 * (chunk_idx + 1)
        frames.append(envelope)

        ref = MagicMock()
        refs.append(ref)

    reader.load_frame.side_effect = frames
    return reader, tuple(refs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_rgb_video_single_mp4(tmp_path: Path) -> None:
    """3-channel video → exactly one .mp4 path attempted via Mp4Writer.write."""
    reader, refs = _make_reader(n_channels=3)
    called_paths: list[Path] = []

    def mock_write(frames, *, fps, output_path):
        called_paths.append(output_path)

    with patch("modlink_core.replay.format.video_mp4.Mp4Writer.write", side_effect=mock_write):
        write_video_mp4(reader, "video", refs, tmp_path)

    assert len(called_paths) == 1
    assert called_paths[0].suffix == ".mp4"


def test_sidecar_csv_exists(tmp_path: Path) -> None:
    """frame_timestamps.csv is written alongside the MP4."""
    reader, refs = _make_reader(n_channels=3, stream_key="cam")

    with patch("modlink_core.replay.format.video_mp4.Mp4Writer.write"):
        write_video_mp4(reader, "video", refs, tmp_path)

    assert (tmp_path / "cam.frame_timestamps.csv").exists()


def test_sidecar_csv_columns(tmp_path: Path) -> None:
    """frame_timestamps.csv has header frame_index,timestamp_ns."""
    reader, refs = _make_reader(n_channels=3, stream_key="cam")

    with patch("modlink_core.replay.format.video_mp4.Mp4Writer.write"):
        write_video_mp4(reader, "video", refs, tmp_path)

    csv_path = tmp_path / "cam.frame_timestamps.csv"
    with csv_path.open(newline="") as f:
        reader_csv = csv.reader(f)
        header = next(reader_csv)

    assert header == ["frame_index", "timestamp_ns"]


def test_invalid_channels_raises(tmp_path: Path) -> None:
    """2-channel video → ValueError."""
    reader, refs = _make_reader(n_channels=2)

    with patch("modlink_core.replay.format.video_mp4.Mp4Writer.write"):
        with pytest.raises(ValueError, match="2 channels"):
            write_video_mp4(reader, "video", refs, tmp_path)


def test_empty_frame_refs_no_output(tmp_path: Path) -> None:
    """Empty frame_refs → no files written, Mp4Writer.write never called."""
    reader = MagicMock()
    descriptor = MagicMock()
    descriptor.stream_key = "cam"
    descriptor.nominal_sample_rate_hz = 30.0
    reader.descriptors.return_value = {"video": descriptor}

    with patch("modlink_core.replay.format.video_mp4.Mp4Writer.write") as mock_write:
        write_video_mp4(reader, "video", (), tmp_path)

    mock_write.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_fps_matches_sample_rate(tmp_path: Path) -> None:
    """Mp4Writer.write is called with fps == descriptor.nominal_sample_rate_hz."""
    reader, refs = _make_reader(n_channels=3, fps=25.0)
    captured: list[float] = []

    def mock_write(frames, *, fps, output_path):
        captured.append(fps)

    with patch("modlink_core.replay.format.video_mp4.Mp4Writer.write", side_effect=mock_write):
        write_video_mp4(reader, "video", refs, tmp_path)

    assert captured == [25.0]
