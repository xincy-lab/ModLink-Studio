from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..reader import RecordedFrameRef, RecordingReader


def write_field_npz(
    reader: RecordingReader,
    stream_id: str,
    frame_refs: tuple[RecordedFrameRef, ...],
    output_path: Path,
) -> None:
    """Write field data as NPZ (default format for field payload).

    NPZ arrays:
      data          shape (C, T_total, H, W), preserves float dtype
      timestamps_ns shape (N_chunks,), int64 — one timestamp per chunk

    Sidecar: <output_path>.meta.json
    """
    descriptor = reader.descriptor(stream_id)
    if descriptor is None:
        raise ValueError(f"stream {stream_id!r} not found in recording")

    channel_names = list(descriptor.channel_names) if descriptor.channel_names else []

    if not frame_refs:
        # Determine spatial dims from descriptor if possible, else default to 0
        n_channels = len(channel_names) if channel_names else 0
        data = np.empty((n_channels, 0, 0, 0), dtype=np.float32)
        timestamps_ns = np.empty((0,), dtype=np.int64)
        shape = [n_channels, 0, 0, 0]
        spatial_dims = [0, 0]
        dtype_str = "float32"
    else:
        data_chunks: list[np.ndarray] = []
        ts_list: list[int] = []

        for ref in frame_refs:
            envelope = reader.load_frame(ref)
            chunk = envelope.data  # shape (C, T, H, W)
            data_chunks.append(chunk)
            ts_list.append(envelope.timestamp_ns)

        data = np.concatenate(data_chunks, axis=1)  # (C, T_total, H, W)
        timestamps_ns = np.array(ts_list, dtype=np.int64)

        c, t_total, h, w = data.shape
        shape = [c, t_total, h, w]
        spatial_dims = [h, w]
        dtype_str = data.dtype.name

        if not channel_names:
            channel_names = [f"ch{i + 1}" for i in range(c)]

    np.savez_compressed(output_path, data=data, timestamps_ns=timestamps_ns)

    meta = {
        "channel_names": channel_names,
        "shape": shape,
        "dtype": dtype_str,
        "stream_key": descriptor.stream_key,
        "device_id": descriptor.device_id,
        "spatial_dims": spatial_dims,
    }
    meta_path = Path(str(output_path) + ".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
