from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..reader import RecordedFrameRef, RecordingReader


def write_raster_npz(
    reader: RecordingReader,
    stream_id: str,
    frame_refs: tuple[RecordedFrameRef, ...],
    output_path: Path,
) -> None:
    """Write raster data as NPZ preserving original dtype.

    NPZ arrays:
      data          shape (C, T_total, L), original dtype preserved
      timestamps_ns shape (N_chunks,), int64 — one timestamp per chunk

    Sidecar: <output_path>.meta.json
    """
    descriptor = reader.descriptor(stream_id)
    if descriptor is None:
        raise ValueError(f"stream {stream_id!r} not found in recording")

    # Determine channel count and line length
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

    # Get line length (L) from descriptor metadata or first frame
    line_length: int | None = (
        descriptor.metadata.get("line_length") if descriptor.metadata else None
    )

    if line_length is None and frame_refs:
        first_data = reader.load_frame(frame_refs[0]).data
        line_length = first_data.shape[2]

    if line_length is None:
        line_length = 0

    if not frame_refs:
        # Determine dtype from descriptor metadata or default to float32
        dtype_str: str = (
            descriptor.metadata.get("dtype", "float32") if descriptor.metadata else "float32"
        )
        data = np.empty((n_channels, 0, line_length), dtype=np.dtype(dtype_str))
        timestamps_ns = np.empty((0,), dtype=np.int64)
    else:
        data_chunks: list[np.ndarray] = []
        ts_list: list[int] = []

        for ref in frame_refs:
            envelope = reader.load_frame(ref)
            chunk = envelope.data  # shape (C, T, L)
            data_chunks.append(chunk)
            ts_list.append(envelope.timestamp_ns)

        data = np.concatenate(data_chunks, axis=1)
        timestamps_ns = np.array(ts_list, dtype=np.int64)

    np.savez_compressed(output_path, data=data, timestamps_ns=timestamps_ns)

    meta = {
        "channel_names": channel_names,
        "shape": list(data.shape),
        "dtype": str(data.dtype),
        "stream_key": descriptor.stream_key,
        "device_id": descriptor.device_id,
    }
    meta_path = Path(str(output_path) + ".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
