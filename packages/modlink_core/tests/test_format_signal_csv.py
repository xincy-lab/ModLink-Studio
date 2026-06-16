from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from modlink_core.replay.format.signal_csv import write_signal_csv
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
        chunk_size=4,
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
    """Build a minimal mock RecordingReader."""
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


def _read_csv(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_sample_level_timestamps(tmp_path: Path) -> None:
    """1 chunk, 4 samples @ 250 Hz, chunk_ts=1_000_000_000 ns.

    Expected timestamps: [1000000000, 1004000000, 1008000000, 1012000000]
    ns_per_sample = 1_000_000_000 / 250 = 4_000_000
    """
    descriptor = _make_descriptor(channel_names=("c1",), sample_rate_hz=250.0)
    ref = _make_ref(timestamp_ns=1_000_000_000)
    data = np.zeros((1, 4), dtype=np.float32)
    reader = _make_reader(descriptor, [(ref, data)])

    out = tmp_path / "out.csv"
    write_signal_csv(reader, "eeg", (ref,), out)

    rows = _read_csv(out)
    assert len(rows) == 5  # header + 4 data rows
    timestamps = [int(row[0]) for row in rows[1:]]
    assert timestamps == [1_000_000_000, 1_004_000_000, 1_008_000_000, 1_012_000_000]


def test_row_count(tmp_path: Path) -> None:
    """3 chunks × chunk_size=10 → 30 data rows."""
    descriptor = _make_descriptor(channel_names=("a", "b"), sample_rate_hz=100.0)
    refs = tuple(_make_ref(timestamp_ns=i * 100_000_000, frame_index=i) for i in range(3))
    frames = [(ref, np.zeros((2, 10), dtype=np.float32)) for ref in refs]
    reader = _make_reader(descriptor, frames)

    out = tmp_path / "out.csv"
    write_signal_csv(reader, "eeg", refs, out)

    rows = _read_csv(out)
    assert len(rows) == 31  # 1 header + 30 data rows


def test_header_uses_channel_names(tmp_path: Path) -> None:
    """descriptor channel_names=('Fp1','Fp2') → header = ['timestamp_ns','Fp1','Fp2']."""
    descriptor = _make_descriptor(channel_names=("Fp1", "Fp2"), sample_rate_hz=250.0)
    reader = _make_reader(descriptor, [])

    out = tmp_path / "out.csv"
    write_signal_csv(reader, "eeg", (), out)

    rows = _read_csv(out)
    assert rows[0] == ["timestamp_ns", "Fp1", "Fp2"]


def test_empty_frame_refs_writes_header_only(tmp_path: Path) -> None:
    """Empty frame_refs → CSV has exactly 1 line (header only)."""
    descriptor = _make_descriptor(channel_names=("x",), sample_rate_hz=100.0)
    reader = _make_reader(descriptor, [])

    out = tmp_path / "out.csv"
    write_signal_csv(reader, "eeg", (), out)

    rows = _read_csv(out)
    assert len(rows) == 1
    assert rows[0][0] == "timestamp_ns"


def test_timestamps_monotonic(tmp_path: Path) -> None:
    """Timestamps across multiple chunks must be strictly increasing."""
    descriptor = _make_descriptor(channel_names=("c1",), sample_rate_hz=500.0)
    # 3 chunks, each 5 samples; chunk spacing = 10_000_000 ns (10 ms)
    refs = tuple(_make_ref(timestamp_ns=i * 10_000_000, frame_index=i) for i in range(3))
    frames = [(ref, np.zeros((1, 5), dtype=np.float32)) for ref in refs]
    reader = _make_reader(descriptor, frames)

    out = tmp_path / "out.csv"
    write_signal_csv(reader, "eeg", refs, out)

    rows = _read_csv(out)
    timestamps = [int(row[0]) for row in rows[1:]]
    assert len(timestamps) == 15
    assert all(timestamps[i] < timestamps[i + 1] for i in range(len(timestamps) - 1))
