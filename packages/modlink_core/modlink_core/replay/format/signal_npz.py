from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..reader import RecordedFrameRef, RecordingReader


def write_signal_npz(
    reader: RecordingReader,
    stream_id: str,
    frame_refs: tuple[RecordedFrameRef, ...],
    output_path: Path,
) -> None:
    """Write signal data as NPZ with sample-level timestamps and sidecar metadata.

    NPZ arrays:
      data          shape (total_samples, n_channels), float32
      timestamps_ns shape (total_samples,), int64 — absolute ns per sample

    Sidecar: <output_path>.meta.json
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

    # Determine channel count
    if descriptor.channel_names:
        n_channels = len(descriptor.channel_names)
        channel_names = list(descriptor.channel_names)
    elif frame_refs:
        first_data = reader.load_frame(frame_refs[0]).data
        n_channels = first_data.shape[0]
        channel_names = [f"ch{i + 1}" for i in range(n_channels)]
    else:
        n_channels = 0
        channel_names = []

    if not frame_refs:
        data = np.empty((0, n_channels), dtype=np.float32)
        timestamps_ns = np.empty((0,), dtype=np.int64)
    else:
        data_chunks: list[np.ndarray] = []
        ts_chunks: list[np.ndarray] = []

        for ref in frame_refs:
            envelope = reader.load_frame(ref)
            chunk = envelope.data  # shape (C, T)
            chunk_ts = envelope.timestamp_ns
            num_samples = chunk.shape[1]

            # Transpose (C, T) → (T, C) and cast to float32
            data_chunks.append(chunk.T.astype(np.float32))

            sample_ts = np.array(
                [int(chunk_ts + i * ns_per_sample) for i in range(num_samples)],
                dtype=np.int64,
            )
            ts_chunks.append(sample_ts)

        data = np.concatenate(data_chunks, axis=0)
        timestamps_ns = np.concatenate(ts_chunks, axis=0)

    np.savez_compressed(output_path, data=data, timestamps_ns=timestamps_ns)

    meta = {
        "channel_names": channel_names,
        "sample_rate_hz": sample_rate_hz,
        "dtype": "float32",
        "device_id": descriptor.device_id,
        "stream_key": descriptor.stream_key,
    }
    meta_path = Path(str(output_path) + ".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
