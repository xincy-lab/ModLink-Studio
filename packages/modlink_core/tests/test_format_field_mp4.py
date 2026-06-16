from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from modlink_core.replay.format.field_mp4 import write_field_mp4
from modlink_core.replay.reader import RecordedFrameRef
from modlink_sdk import FrameEnvelope, StreamDescriptor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_descriptor(
    *,
    stream_key: str = "field",
    channel_names: tuple[str, ...] = ("ch1", "ch2"),
    nominal_sample_rate_hz: float = 10.0,
) -> StreamDescriptor:
    return StreamDescriptor(
        device_id="test.01",
        stream_key=stream_key,
        payload_type="field",
        nominal_sample_rate_hz=nominal_sample_rate_hz,
        chunk_size=2,
        channel_names=channel_names,
        display_name="Test Field",
        metadata={},
    )


def _make_ref(
    timestamp_ns: int, frame_index: int = 0, stream_id: str = "field"
) -> RecordedFrameRef:
    return RecordedFrameRef(
        stream_id=stream_id,
        frame_index=frame_index,
        timestamp_ns=timestamp_ns,
        seq=frame_index,
        file_name="frames.bin",
        relative_timestamp_ns=0,
    )


def _make_reader(
    descriptor: StreamDescriptor,
    frames: list[tuple[RecordedFrameRef, np.ndarray]],
    stream_id: str = "field",
    value_range: tuple[float, float] | None = (0.0, 1.0),
) -> MagicMock:
    reader = MagicMock()
    reader.descriptors.return_value = {stream_id: descriptor}
    reader.stream_value_range.return_value = value_range

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


def _field_data(n_channels: int = 2, t: int = 2, h: int = 3, w: int = 4) -> np.ndarray:
    """Return float32 array shape (C, T, H, W)."""
    size = n_channels * t * h * w
    return np.arange(size, dtype=np.float32).reshape(n_channels, t, h, w)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_one_mp4_per_channel(tmp_path: Path) -> None:
    """2-channel field → Mp4Writer.write called twice (one per channel)."""
    descriptor = _make_descriptor(channel_names=("ch1", "ch2"))
    ref = _make_ref(timestamp_ns=1_000_000_000)
    data = _field_data(n_channels=2, t=2, h=3, w=4)
    reader = _make_reader(descriptor, [(ref, data)])

    write_calls: list[dict] = []

    def mock_write(frames, *, fps, output_path):
        write_calls.append({"frames": list(frames), "fps": fps, "output_path": output_path})

    with patch("modlink_core.replay.format.field_mp4.Mp4Writer.write", side_effect=mock_write):
        write_field_mp4(reader, "field", (ref,), tmp_path)

    assert len(write_calls) == 2
    paths = {c["output_path"] for c in write_calls}
    assert tmp_path / "field_ch01.mp4" in paths
    assert tmp_path / "field_ch02.mp4" in paths


def test_sidecar_csv_per_channel(tmp_path: Path) -> None:
    """2-channel field → 2 frame_timestamps.csv files written."""
    descriptor = _make_descriptor(channel_names=("ch1", "ch2"))
    ref = _make_ref(timestamp_ns=1_000_000_000)
    data = _field_data(n_channels=2, t=2, h=3, w=4)
    reader = _make_reader(descriptor, [(ref, data)])

    with patch("modlink_core.replay.format.field_mp4.Mp4Writer.write"):
        write_field_mp4(reader, "field", (ref,), tmp_path)

    assert (tmp_path / "field_ch01.frame_timestamps.csv").is_file()
    assert (tmp_path / "field_ch02.frame_timestamps.csv").is_file()


def test_sidecar_csv_columns(tmp_path: Path) -> None:
    """CSV has frame_index,timestamp_ns header and correct row count."""
    descriptor = _make_descriptor(channel_names=("ch1", "ch2"), nominal_sample_rate_hz=10.0)
    ref = _make_ref(timestamp_ns=1_000_000_000)
    data = _field_data(n_channels=2, t=3, h=3, w=4)
    reader = _make_reader(descriptor, [(ref, data)])

    with patch("modlink_core.replay.format.field_mp4.Mp4Writer.write"):
        write_field_mp4(reader, "field", (ref,), tmp_path)

    csv_path = tmp_path / "field_ch01.frame_timestamps.csv"
    with csv_path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    assert list(rows[0].keys()) == ["frame_index", "timestamp_ns"]
    # 3 time-steps in the single chunk
    assert len(rows) == 3
    # first frame timestamp == chunk timestamp
    assert int(rows[0]["timestamp_ns"]) == 1_000_000_000
    # second frame offset by 1/fps seconds in ns
    assert int(rows[1]["timestamp_ns"]) == 1_000_000_000 + int(1e9 / 10.0)


def test_empty_frame_refs_no_output(tmp_path: Path) -> None:
    """Empty frame_refs → no files written, no errors."""
    descriptor = _make_descriptor()
    reader = _make_reader(descriptor, [])

    with patch("modlink_core.replay.format.field_mp4.Mp4Writer.write") as mock_write:
        write_field_mp4(reader, "field", (), tmp_path)

    mock_write.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_fps_matches_sample_rate(tmp_path: Path) -> None:
    """fps passed to Mp4Writer.write equals descriptor.nominal_sample_rate_hz."""
    descriptor = _make_descriptor(nominal_sample_rate_hz=25.0)
    ref = _make_ref(timestamp_ns=0)
    data = _field_data(n_channels=2, t=1, h=3, w=4)
    reader = _make_reader(descriptor, [(ref, data)])

    captured_fps: list[float] = []

    def mock_write(frames, *, fps, output_path):
        captured_fps.append(fps)

    with patch("modlink_core.replay.format.field_mp4.Mp4Writer.write", side_effect=mock_write):
        write_field_mp4(reader, "field", (ref,), tmp_path)

    assert all(fps == 25.0 for fps in captured_fps)
    assert len(captured_fps) == 2  # one call per channel
