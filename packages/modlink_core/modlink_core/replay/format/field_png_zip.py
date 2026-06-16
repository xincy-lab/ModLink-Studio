from __future__ import annotations

import io
import zipfile
from pathlib import Path

from PIL import Image

from ..reader import RecordingReader
from .colormap import apply_viridis
from .scaler import GlobalMinMaxScaler


def write_field_png_zip(
    reader: RecordingReader,
    stream_id: str,
    frame_refs: tuple,
    output_path: Path,
) -> None:
    """Write field data frames as a PNG sequence (viridis colormap) in a ZIP file.

    For each chunk, for each time-step T, for each channel C: one PNG.
    File naming: frame_{global_frame_index:06d}_ch{channel_index+1:02d}.png
    where global_frame_index increments per (chunk, t) pair.

    Includes index.csv with columns: frame_index,channel,timestamp_ns,file_in_zip.
    Empty frame_refs → ZIP with only index.csv (header only).
    """
    csv_lines = ["frame_index,channel,timestamp_ns,file_in_zip"]

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if frame_refs:
            scaler = GlobalMinMaxScaler(reader)
            range_result = scaler.get_range(stream_id)
            if range_result is None:
                raise ValueError(
                    f"stream {stream_id!r} has no frames — cannot determine value range"
                )
            vmin, vmax = range_result

            global_frame_index = 0
            for ref in frame_refs:
                envelope = reader.load_frame(ref)
                data = envelope.data  # shape (C, T, H, W)
                n_channels = data.shape[0]
                n_timesteps = data.shape[1]
                timestamp_ns = envelope.timestamp_ns

                for t in range(n_timesteps):
                    for c in range(n_channels):
                        rgb = apply_viridis(data[c, t], vmin, vmax)  # (H, W, 3) uint8
                        buf = io.BytesIO()
                        Image.fromarray(rgb).save(buf, format="PNG")

                        filename = f"frame_{global_frame_index:06d}_ch{c + 1:02d}.png"
                        zf.writestr(filename, buf.getvalue())
                        csv_lines.append(f"{global_frame_index},{c + 1},{timestamp_ns},{filename}")

                    global_frame_index += 1

        zf.writestr("index.csv", "\n".join(csv_lines) + "\n")
