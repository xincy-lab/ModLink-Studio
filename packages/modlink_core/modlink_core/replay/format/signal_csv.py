from __future__ import annotations

import csv
from pathlib import Path

from ..reader import RecordedFrameRef, RecordingReader


def write_signal_csv(
    reader: RecordingReader,
    stream_id: str,
    frame_refs: tuple[RecordedFrameRef, ...],
    output_path: Path,
) -> None:
    """Write signal data as CSV with one row per sample and sample-level timestamps.

    Header: timestamp_ns,<ch1>,<ch2>,...
    timestamp_ns for sample i in a chunk = chunk.timestamp_ns + i * (1_000_000_000 / sample_rate_hz)
    """
    descriptor = reader.descriptor(stream_id)
    if descriptor is None:
        raise ValueError(f"stream {stream_id!r} not found in recording")

    sample_rate_hz = descriptor.nominal_sample_rate_hz
    if sample_rate_hz <= 0:
        raise ValueError(
            f"stream {stream_id!r} has invalid nominal_sample_rate_hz {sample_rate_hz!r}"
        )

    ns_per_sample = 1_000_000_000 / sample_rate_hz

    # Build channel header names
    if descriptor.channel_names:
        channel_headers = list(descriptor.channel_names)
    else:
        # Determine channel count from first frame if available
        if frame_refs:
            first_data = reader.load_frame(frame_refs[0]).data
            channel_count = first_data.shape[0]
        else:
            channel_count = 0
        channel_headers = [f"ch{i + 1}" for i in range(channel_count)]

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp_ns", *channel_headers])

        for ref in frame_refs:
            envelope = reader.load_frame(ref)
            data = envelope.data  # shape (C, T)
            chunk_ts = envelope.timestamp_ns
            num_samples = data.shape[1]

            for i in range(num_samples):
                sample_ts = int(chunk_ts + i * ns_per_sample)
                writer.writerow([sample_ts, *data[:, i].tolist()])
