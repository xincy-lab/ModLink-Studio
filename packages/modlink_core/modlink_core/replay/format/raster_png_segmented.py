from __future__ import annotations

import io
import json
import math
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

from ..reader import RecordedFrameRef, RecordingReader
from .colormap import apply_viridis
from .scaler import GlobalMinMaxScaler


def write_raster_waterfall_segmented_zip(
    reader: RecordingReader,
    stream_id: str,
    frame_refs: tuple[RecordedFrameRef, ...],
    segment_chunks: int,
    output_path: Path,
) -> None:
    """Write raster data as segmented waterfall PNGs packed into a ZIP file.

    Each segment contains up to `segment_chunks` chunks. For each segment and
    channel, a PNG is written in-memory and stored in the ZIP as:
        {stream_key}_ch{n+1:02d}_seg{s+1:04d}.png

    A meta.json is always included in the ZIP.
    Empty frame_refs → ZIP with only meta.json.
    """
    descriptor = reader.descriptors()[stream_id]
    stream_key = descriptor.stream_key
    channel_names = list(descriptor.channel_names)

    if not frame_refs:
        meta = {
            "channel_names": channel_names,
            "segment_chunks": segment_chunks,
            "total_segments": 0,
            "value_range": None,
            "shape": [len(channel_names), 0, 0],
        }
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("meta.json", json.dumps(meta, indent=2))
        return

    scaler = GlobalMinMaxScaler(reader)
    range_result = scaler.get_range(stream_id)
    if range_result is None:
        raise ValueError(f"stream {stream_id!r} has no frames — cannot determine value range")
    vmin, vmax = range_result

    # Load all frames; each frame.data has shape (C, T, L)
    envelopes = [reader.load_frame(ref) for ref in frame_refs]
    n_channels = envelopes[0].data.shape[0]
    line_length = envelopes[0].data.shape[2]
    t_total = sum(env.data.shape[1] for env in envelopes)

    if not channel_names:
        channel_names = [f"ch{i + 1}" for i in range(n_channels)]

    total_segments = math.ceil(len(envelopes) / segment_chunks)
    segments = [
        envelopes[s * segment_chunks : (s + 1) * segment_chunks] for s in range(total_segments)
    ]

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for s, seg_envelopes in enumerate(segments):
            for n in range(n_channels):
                chunks = [env.data[n] for env in seg_envelopes]  # each (T, L)
                seg_data = np.concatenate(chunks, axis=0)  # (T_seg, L)
                rgb = apply_viridis(seg_data, vmin, vmax)  # (T_seg, L, 3) uint8
                buf = io.BytesIO()
                Image.fromarray(rgb).save(buf, format="PNG")
                filename = f"{stream_key}_ch{n + 1:02d}_seg{s + 1:04d}.png"
                zf.writestr(filename, buf.getvalue())

        meta = {
            "channel_names": channel_names,
            "segment_chunks": segment_chunks,
            "total_segments": total_segments,
            "value_range": [vmin, vmax],
            "shape": [n_channels, t_total, line_length],
        }
        zf.writestr("meta.json", json.dumps(meta, indent=2))
