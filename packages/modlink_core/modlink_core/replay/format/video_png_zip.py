from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

from ..reader import RecordedFrameRef, RecordingReader


def write_video_png_zip(
    reader: RecordingReader,
    stream_id: str,
    frame_refs: tuple[RecordedFrameRef, ...],
    output_path: Path,
) -> None:
    """Write video frames as a PNG sequence inside a ZIP file.

    Each time-step T within each chunk becomes one PNG file named
    frame_{global_frame_index:06d}.png. An index.csv is also written
    inside the ZIP with columns: frame_index,timestamp_ns,file_in_zip.

    Video data shape per chunk: (C, T, H, W) uint8.
      C=1 → grayscale ('L'), C=3 → RGB, C=4 → RGBA.
    """
    descriptor = reader.descriptors()[stream_id]
    sample_rate_hz = descriptor.nominal_sample_rate_hz
    ns_per_sample = 1_000_000_000 / sample_rate_hz

    index_rows: list[tuple[int, int, str]] = []  # (frame_index, timestamp_ns, file_in_zip)
    global_frame_index = 0

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for ref in frame_refs:
            envelope = reader.load_frame(ref)
            data = envelope.data  # (C, T, H, W) uint8
            chunk_ts = envelope.timestamp_ns
            n_channels, n_timesteps = data.shape[0], data.shape[1]

            for t in range(n_timesteps):
                frame_arr = data[:, t, :, :]  # (C, H, W)
                img = _array_to_image(frame_arr, n_channels)
                png_bytes = _image_to_png_bytes(img)

                file_name = f"frame_{global_frame_index:06d}.png"
                zf.writestr(file_name, png_bytes)

                timestamp_ns = int(chunk_ts + t * ns_per_sample)
                index_rows.append((global_frame_index, timestamp_ns, file_name))
                global_frame_index += 1

        # Write index.csv
        csv_lines = ["frame_index,timestamp_ns,file_in_zip"]
        for frame_idx, ts_ns, fname in index_rows:
            csv_lines.append(f"{frame_idx},{ts_ns},{fname}")
        zf.writestr("index.csv", "\n".join(csv_lines))


def _array_to_image(frame_arr: np.ndarray, n_channels: int) -> Image.Image:
    """Convert a (C, H, W) uint8 array to a Pillow Image."""
    if n_channels == 1:
        return Image.fromarray(frame_arr[0], mode="L")
    if n_channels == 3:
        # (3, H, W) → (H, W, 3)
        return Image.fromarray(np.transpose(frame_arr, (1, 2, 0)), mode="RGB")
    if n_channels == 4:
        # (4, H, W) → (H, W, 4)
        return Image.fromarray(np.transpose(frame_arr, (1, 2, 0)), mode="RGBA")
    raise ValueError(
        f"unsupported channel count {n_channels!r}: expected 1 (grayscale), 3 (RGB), or 4 (RGBA)"
    )


def _image_to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
