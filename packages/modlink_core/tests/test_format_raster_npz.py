from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from modlink_core.replay.format.raster_npz import write_raster_npz
from modlink_core.replay.reader import RecordedFrameRef
from modlink_sdk import FrameEnvelope, StreamDescriptor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_descriptor(
    *,
    channel_names: tuple[str, ...] = ("ch1", "ch2"),
    payload_type: str = "raster",
) -> StreamDescriptor:
    return StreamDescriptor(
        device_id="test.01",
        stream_key="raster",
        payload_type=payload_type,
        nominal_sample_rate_hz=100.0,
        chunk_size=4,
        channel_names=channel_names,
        display_name="Test Raster",
        metadata={},
    )


def _make_ref(timestamp_ns: int, frame_index: int = 0) -> RecordedFrameRef:
    return RecordedFrameRef(
        stream_id="raster",
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
    reader.descriptor.return_value = descriptor

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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_shape(tmp_path: Path) -> None:
    """2-channel raster, 3 chunks each (T=4, L=8) → data.shape == (2, 12, 8)."""
    descriptor = _make_descriptor(channel_names=("ch1", "ch2"))
    refs = tuple(_make_ref(timestamp_ns=i * 100_000_000, frame_index=i) for i in range(3))
    frames = [(ref, np.zeros((2, 4, 8), dtype=np.int16)) for ref in refs]
    reader = _make_reader(descriptor, frames)

    out = tmp_path / "raster.npz"
    write_raster_npz(reader, "raster", refs, out)

    npz = np.load(out)
    assert npz["data"].shape == (2, 12, 8)


def test_dtype_preserved(tmp_path: Path) -> None:
    """int16 input → data.dtype == int16 (no float promotion)."""
    descriptor = _make_descriptor(channel_names=("ch1", "ch2"))
    refs = tuple(_make_ref(timestamp_ns=i * 100_000_000, frame_index=i) for i in range(2))
    frames = [(ref, np.zeros((2, 4, 8), dtype=np.int16)) for ref in refs]
    reader = _make_reader(descriptor, frames)

    out = tmp_path / "raster.npz"
    write_raster_npz(reader, "raster", refs, out)

    npz = np.load(out)
    assert npz["data"].dtype == np.int16


def test_timestamps_shape(tmp_path: Path) -> None:
    """3 chunks → timestamps_ns.shape == (3,)."""
    descriptor = _make_descriptor(channel_names=("ch1", "ch2"))
    refs = tuple(_make_ref(timestamp_ns=i * 100_000_000, frame_index=i) for i in range(3))
    frames = [(ref, np.zeros((2, 4, 8), dtype=np.int16)) for ref in refs]
    reader = _make_reader(descriptor, frames)

    out = tmp_path / "raster.npz"
    write_raster_npz(reader, "raster", refs, out)

    npz = np.load(out)
    assert npz["timestamps_ns"].shape == (3,)
    assert npz["timestamps_ns"].dtype == np.int64


def test_sidecar_json(tmp_path: Path) -> None:
    """meta.json exists with channel_names key."""
    descriptor = _make_descriptor(channel_names=("row1", "row2"))
    refs = (_make_ref(timestamp_ns=0),)
    frames = [(refs[0], np.zeros((2, 4, 8), dtype=np.int16))]
    reader = _make_reader(descriptor, frames)

    out = tmp_path / "raster.npz"
    write_raster_npz(reader, "raster", refs, out)

    meta_path = tmp_path / "raster.npz.meta.json"
    assert meta_path.is_file()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert "channel_names" in meta
    assert meta["channel_names"] == ["row1", "row2"]


def test_empty_frame_refs(tmp_path: Path) -> None:
    """Empty frame_refs → data.shape[1] == 0."""
    descriptor = _make_descriptor(channel_names=("ch1", "ch2"))
    reader = _make_reader(descriptor, [])

    out = tmp_path / "raster.npz"
    write_raster_npz(reader, "raster", (), out)

    npz = np.load(out)
    assert npz["data"].shape[1] == 0
    assert npz["timestamps_ns"].shape == (0,)
