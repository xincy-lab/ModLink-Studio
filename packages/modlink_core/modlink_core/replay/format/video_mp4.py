from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from ..reader import RecordingReader
from .mp4_writer import Mp4Writer


def write_video_mp4(
    reader: RecordingReader,
    stream_id: str,
    frame_refs: tuple,
    output_dir: Path,
) -> None:
    """Write video stream as a single MP4 with a frame_timestamps sidecar CSV.

    Frame shape: (C, T, H, W) uint8.
    C==1: grayscale (H, W); C==3: RGB (H, W, 3); C==4: RGBA (H, W, 4).
    Sidecar: {stream_key}.frame_timestamps.csv with columns frame_index,timestamp_ns.
    Empty frame_refs → returns silently without writing any files.
    """
    if not frame_refs:
        return

    descriptor = reader.descriptors()[stream_id]
    stream_key = descriptor.stream_key
    fps = descriptor.nominal_sample_rate_hz
    ns_per_frame = 1_000_000_000 / fps

    frames: list[np.ndarray] = []
    timestamps: list[tuple[int, int]] = []
    frame_index = 0
    c: int | None = None

    for ref in frame_refs:
        envelope = reader.load_frame(ref)
        data = envelope.data  # (C, T, H, W) uint8
        chunk_ts = envelope.timestamp_ns

        if c is None:
            c = data.shape[0]
            if c not in (1, 3, 4):
                raise ValueError(f"video stream has {c} channels; expected 1, 3, or 4")

        n_timesteps = data.shape[1]
        for t in range(n_timesteps):
            chw = data[:, t, :, :]  # (C, H, W)
            if c == 1:
                frame = chw[0]  # (H, W)
            else:
                frame = np.transpose(chw, (1, 2, 0))  # (H, W, C)
            frames.append(frame)
            timestamps.append((frame_index, int(chunk_ts + t * ns_per_frame)))
            frame_index += 1

    Mp4Writer.write(frames, fps=fps, output_path=output_dir / f"{stream_key}.mp4")

    csv_path = output_dir / f"{stream_key}.frame_timestamps.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["frame_index", "timestamp_ns"])
        writer.writerows(timestamps)
