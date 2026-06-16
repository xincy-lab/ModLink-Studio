from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from modlink_core.replay.format.field_npz import write_field_npz
from modlink_core.replay.reader import RecordedFrameRef
from modlink_sdk import FrameEnvelope, StreamDescriptor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_descriptor(
    *,
    channel_names: tuple[str, ...] = ("ch1", "ch2"),
) -> StreamDescriptor:
    return StreamDescriptor(
        device_id="test.01",
        stream_key="field",
        payload_type="field",
        nominal_sample_rate_hz=0.0,
        chunk_size=1,
        channel_names=channel_names,
        display_name="Test Field",
        metadata={},
    )


def _make_ref(timestamp_ns: int, frame_index: int = 0) -> RecordedFrameRef:
    return RecordedFrameRef(
        stream_id="field",
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
    """2-channel field, 3 chunks each (T=1, H=4, W=5) → data.shape == (2, 3, 4, 5)."""
    descriptor = _make_descriptor(channel_names=("ch1", "ch2"))
    refs = tuple(_make_ref(timestamp_ns=i * 1_000_000, frame_index=i) for i in range(3))
    frames = [(ref, np.zeros((2, 1, 4, 5), dtype=np.float32)) for ref in refs]
    reader = _make_reader(descriptor, frames)

    out = tmp_path / "field.npz"
    write_field_npz(reader, "field", refs, out)

    npz = np.load(out)
    assert npz["data"].shape == (2, 3, 4, 5)


def test_dtype_preserved(tmp_path: Path) -> None:
    """float32 input → data.dtype == float32 (no promotion)."""
    descriptor = _make_descriptor(channel_names=("ch1", "ch2"))
    refs = tuple(_make_ref(timestamp_ns=i * 1_000_000, frame_index=i) for i in range(3))
    frames = [(ref, np.zeros((2, 1, 4, 5), dtype=np.float32)) for ref in refs]
    reader = _make_reader(descriptor, frames)

    out = tmp_path / "field.npz"
    write_field_npz(reader, "field", refs, out)

    npz = np.load(out)
    assert npz["data"].dtype == np.float32


def test_sidecar_spatial_dims(tmp_path: Path) -> None:
    """meta.json has spatial_dims: [4, 5]."""
    descriptor = _make_descriptor(channel_names=("ch1", "ch2"))
    refs = tuple(_make_ref(timestamp_ns=i * 1_000_000, frame_index=i) for i in range(3))
    frames = [(ref, np.zeros((2, 1, 4, 5), dtype=np.float32)) for ref in refs]
    reader = _make_reader(descriptor, frames)

    out = tmp_path / "field.npz"
    write_field_npz(reader, "field", refs, out)

    meta = json.loads((tmp_path / "field.npz.meta.json").read_text(encoding="utf-8"))
    assert meta["spatial_dims"] == [4, 5]


def test_timestamps_shape(tmp_path: Path) -> None:
    """3 chunks → timestamps_ns.shape == (3,)."""
    descriptor = _make_descriptor(channel_names=("ch1", "ch2"))
    refs = tuple(_make_ref(timestamp_ns=i * 1_000_000, frame_index=i) for i in range(3))
    frames = [(ref, np.zeros((2, 1, 4, 5), dtype=np.float32)) for ref in refs]
    reader = _make_reader(descriptor, frames)

    out = tmp_path / "field.npz"
    write_field_npz(reader, "field", refs, out)

    npz = np.load(out)
    assert npz["timestamps_ns"].shape == (3,)
