from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from modlink_core.replay.format.signal_npz import write_signal_npz
from modlink_core.replay.reader import RecordedFrameRef
from modlink_sdk import FrameEnvelope, StreamDescriptor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_descriptor(
    *,
    channel_names: tuple[str, ...] = ("ch1", "ch2"),
    sample_rate_hz: float = 250.0,
) -> StreamDescriptor:
    return StreamDescriptor(
        device_id="test.01",
        stream_key="eeg",
        payload_type="signal",
        nominal_sample_rate_hz=sample_rate_hz,
        chunk_size=10,
        channel_names=channel_names,
        display_name="Test EEG",
        metadata={},
    )


def _make_ref(timestamp_ns: int, frame_index: int = 0) -> RecordedFrameRef:
    return RecordedFrameRef(
        stream_id="eeg",
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


def test_npz_shape(tmp_path: Path) -> None:
    """3 chunks × chunk_size=10, 2 channels → data.shape == (30, 2)."""
    descriptor = _make_descriptor(channel_names=("ch1", "ch2"), sample_rate_hz=100.0)
    refs = tuple(_make_ref(timestamp_ns=i * 100_000_000, frame_index=i) for i in range(3))
    frames = [(ref, np.zeros((2, 10), dtype=np.float32)) for ref in refs]
    reader = _make_reader(descriptor, frames)

    out = tmp_path / "signal.npz"
    write_signal_npz(reader, "eeg", refs, out)

    npz = np.load(out)
    assert npz["data"].shape == (30, 2)


def test_timestamps_dtype(tmp_path: Path) -> None:
    """timestamps_ns array must have dtype int64."""
    descriptor = _make_descriptor(channel_names=("ch1", "ch2"), sample_rate_hz=100.0)
    refs = tuple(_make_ref(timestamp_ns=i * 100_000_000, frame_index=i) for i in range(2))
    frames = [(ref, np.zeros((2, 10), dtype=np.float32)) for ref in refs]
    reader = _make_reader(descriptor, frames)

    out = tmp_path / "signal.npz"
    write_signal_npz(reader, "eeg", refs, out)

    npz = np.load(out)
    assert npz["timestamps_ns"].dtype == np.int64


def test_sidecar_json_exists(tmp_path: Path) -> None:
    """.meta.json sidecar file is created alongside the .npz."""
    descriptor = _make_descriptor(channel_names=("ch1", "ch2"), sample_rate_hz=100.0)
    refs = (_make_ref(timestamp_ns=0),)
    frames = [(refs[0], np.zeros((2, 10), dtype=np.float32))]
    reader = _make_reader(descriptor, frames)

    out = tmp_path / "signal.npz"
    write_signal_npz(reader, "eeg", refs, out)

    assert (tmp_path / "signal.npz.meta.json").is_file()


def test_sidecar_has_channel_names(tmp_path: Path) -> None:
    """Sidecar JSON contains channel_names key with correct values."""
    descriptor = _make_descriptor(channel_names=("Fp1", "Fp2"), sample_rate_hz=250.0)
    refs = (_make_ref(timestamp_ns=0),)
    frames = [(refs[0], np.zeros((2, 10), dtype=np.float32))]
    reader = _make_reader(descriptor, frames)

    out = tmp_path / "signal.npz"
    write_signal_npz(reader, "eeg", refs, out)

    meta = json.loads((tmp_path / "signal.npz.meta.json").read_text(encoding="utf-8"))
    assert "channel_names" in meta
    assert meta["channel_names"] == ["Fp1", "Fp2"]


def test_empty_frame_refs(tmp_path: Path) -> None:
    """Empty frame_refs → data.shape == (0, n_channels), timestamps_ns.shape == (0,)."""
    descriptor = _make_descriptor(channel_names=("ch1", "ch2"), sample_rate_hz=100.0)
    reader = _make_reader(descriptor, [])

    out = tmp_path / "signal.npz"
    write_signal_npz(reader, "eeg", (), out)

    npz = np.load(out)
    assert npz["data"].shape == (0, 2)
    assert npz["timestamps_ns"].shape == (0,)
