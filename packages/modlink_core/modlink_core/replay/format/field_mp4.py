from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from ..reader import RecordedFrameRef, RecordingReader
from .colormap import apply_viridis
from .mp4_writer import Mp4Writer
from .scaler import GlobalMinMaxScaler


def write_field_mp4(
    reader: RecordingReader,
    stream_id: str,
    frame_refs: tuple[RecordedFrameRef, ...],
    output_dir: Path,
) -> None:
    """Write field data as per-channel MP4 files with frame_timestamps sidecar.

    For each channel n, writes:
      <stream_key>_ch<n+1:02d>.mp4
      <stream_key>_ch<n+1:02d>.frame_timestamps.csv

    Frames are colorized with viridis using global min/max across all chunks.
    Empty frame_refs → returns silently with no files written.
    """
    if not frame_refs:
        return

    descriptor = reader.descriptors()[stream_id]
    stream_key = descriptor.stream_key
    fps = descriptor.nominal_sample_rate_hz
    ns_per_sample = 1e9 / fps if fps > 0 else 0.0

    scaler = GlobalMinMaxScaler(reader)
    range_result = scaler.get_range(stream_id)
    if range_result is None:
        vmin, vmax = 0.0, 1.0
    else:
        vmin, vmax = range_result

    # Load all chunks once; collect per-channel frame lists and timestamps
    # Each chunk envelope.data shape: (C, T, H, W)
    chunks: list[tuple[int, np.ndarray]] = []  # (timestamp_ns, data)
    for ref in frame_refs:
        envelope = reader.load_frame(ref)
        chunks.append((envelope.timestamp_ns, envelope.data))

    n_channels = chunks[0][1].shape[0]

    for ch_idx in range(n_channels):
        frames_rgb: list[np.ndarray] = []
        timestamp_rows: list[tuple[int, int]] = []  # (frame_index, timestamp_ns)
        global_frame_idx = 0

        for chunk_ts, chunk_data in chunks:
            # chunk_data[ch_idx] shape: (T, H, W)
            channel_chunk = chunk_data[ch_idx]
            t_count = channel_chunk.shape[0]
            for t in range(t_count):
                frame_hw = channel_chunk[t]  # (H, W)
                rgb = apply_viridis(frame_hw, vmin, vmax)  # (H, W, 3) uint8
                frames_rgb.append(rgb)
                ts_ns = int(chunk_ts + t * ns_per_sample)
                timestamp_rows.append((global_frame_idx, ts_ns))
                global_frame_idx += 1

        stem = f"{stream_key}_ch{ch_idx + 1:02d}"
        mp4_path = output_dir / f"{stem}.mp4"
        Mp4Writer.write(frames_rgb, fps=fps, output_path=mp4_path)

        csv_path = output_dir / f"{stem}.frame_timestamps.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["frame_index", "timestamp_ns"])
            writer.writerows(timestamp_rows)
