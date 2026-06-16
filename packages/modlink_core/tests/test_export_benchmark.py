from __future__ import annotations

import csv
import time
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from modlink_core.replay.format.signal_csv import write_signal_csv
from modlink_core.replay.reader import RecordedFrameRef
from modlink_sdk import FrameEnvelope, StreamDescriptor

pytestmark = pytest.mark.slow


_NUM_FRAMES = 1000
_NUM_CHANNELS = 64
_CHUNK_SIZE = 64
_SAMPLE_RATE_HZ = 1000.0
_THRESHOLD_SECONDS = 30.0


def _build_reader(
    descriptor: StreamDescriptor,
    refs: tuple[RecordedFrameRef, ...],
    payloads: list[np.ndarray],
) -> MagicMock:
    reader = MagicMock()
    reader.descriptor.return_value = descriptor

    payload_by_ref = dict(zip(refs, payloads, strict=True))

    def load_frame(ref: RecordedFrameRef) -> FrameEnvelope:
        return FrameEnvelope(
            device_id=descriptor.device_id,
            stream_key=descriptor.stream_key,
            timestamp_ns=ref.timestamp_ns,
            data=payload_by_ref[ref],
            seq=ref.seq,
        )

    reader.load_frame.side_effect = load_frame
    return reader


def test_large_signal_csv_export_under_threshold(
    tmp_path: Path,
    descriptor_factory,
) -> None:
    """Benchmark: 1000 frames * 64 channels * 64 samples => 64k rows of CSV.

    Threshold is intentionally loose (30s) — this is a regression guard, not
    a CI gate. If this ever fails, signal_csv has likely regressed badly.
    """
    rng = np.random.default_rng(seed=20260531)

    descriptor = descriptor_factory(
        payload_type="signal",
        nominal_sample_rate_hz=_SAMPLE_RATE_HZ,
        chunk_size=_CHUNK_SIZE,
        channel_names=tuple(f"c{i}" for i in range(_NUM_CHANNELS)),
    )

    chunk_period_ns = int(1_000_000_000 / _SAMPLE_RATE_HZ * _CHUNK_SIZE)
    refs = tuple(
        RecordedFrameRef(
            stream_id=descriptor.stream_key,
            frame_index=i,
            timestamp_ns=i * chunk_period_ns,
            seq=i,
            file_name="frames.bin",
            relative_timestamp_ns=i * chunk_period_ns,
        )
        for i in range(_NUM_FRAMES)
    )
    payloads = [
        rng.standard_normal((_NUM_CHANNELS, _CHUNK_SIZE)).astype(np.float32)
        for _ in range(_NUM_FRAMES)
    ]

    reader = _build_reader(descriptor, refs, payloads)
    output_path = tmp_path / "bench_signal.csv"

    start = time.perf_counter()
    write_signal_csv(reader, descriptor.stream_key, refs, output_path)
    elapsed = time.perf_counter() - start

    print(
        f"\nSignal CSV bench: {_NUM_FRAMES} frames x {_NUM_CHANNELS} channels "
        f"x {_CHUNK_SIZE} samples written in {elapsed:.2f}s "
        f"({output_path.stat().st_size / 1_048_576:.1f} MiB)"
    )

    assert output_path.exists()
    assert output_path.stat().st_size > 0

    expected_rows = _NUM_FRAMES * _CHUNK_SIZE + 1  # +1 for header
    with output_path.open("r", encoding="utf-8", newline="") as f:
        reader_csv = csv.reader(f)
        header = next(reader_csv)
        first_row = next(reader_csv)
        assert len(header) == _NUM_CHANNELS + 1  # timestamp_ns + channels
        assert header[0] == "timestamp_ns"
        assert len(first_row) == len(header)
        # Drain to count remaining rows cheaply
        remaining = sum(1 for _ in reader_csv)
        # header + first_row already consumed
        assert remaining + 2 == expected_rows

    assert elapsed < _THRESHOLD_SECONDS, (
        f"Bench too slow: {elapsed:.2f}s (threshold {_THRESHOLD_SECONDS}s)"
    )
