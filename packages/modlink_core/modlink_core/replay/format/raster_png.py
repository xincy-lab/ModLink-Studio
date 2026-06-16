from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from ..reader import RecordedFrameRef, RecordingReader
from .colormap import apply_viridis
from .scaler import GlobalMinMaxScaler


def write_raster_waterfall_png(
    reader: RecordingReader,
    stream_id: str,
    frame_refs: tuple[RecordedFrameRef, ...],
    output_dir: Path,
) -> None:
    """Write raster data as per-channel waterfall PNG images using viridis colormap.

    For each channel, all chunks are stacked along the time axis and rendered as a
    single PNG where rows = time steps and columns = lag/frequency bins.

    Sidecar: <stream_key>_waterfall.meta.json
    Empty frame_refs → returns silently, no files written.
    """
    if not frame_refs:
        return

    descriptor = reader.descriptors()[stream_id]
    stream_key = descriptor.stream_key
    channel_names = list(descriptor.channel_names)

    scaler = GlobalMinMaxScaler(reader)
    range_result = scaler.get_range(stream_id)
    if range_result is None:
        raise ValueError(f"stream {stream_id!r} has no frames — cannot determine value range")
    vmin, vmax = range_result

    # Load all frames once; each frame.data has shape (C, T, L)
    envelopes = [reader.load_frame(ref) for ref in frame_refs]
    n_channels = envelopes[0].data.shape[0]

    # Fallback channel names if descriptor has none
    if not channel_names:
        channel_names = [f"ch{i + 1}" for i in range(n_channels)]

    t_total = sum(env.data.shape[1] for env in envelopes)
    line_length = envelopes[0].data.shape[2]

    for n in range(n_channels):
        chunks = [env.data[n] for env in envelopes]  # each (T, L)
        channel_data = np.concatenate(chunks, axis=0)  # (T_total, L)
        rgb = apply_viridis(channel_data, vmin, vmax)  # (T_total, L, 3) uint8
        Image.fromarray(rgb).save(output_dir / f"{stream_key}_ch{n + 1}_waterfall.png")

    time_range_ns = [envelopes[0].timestamp_ns, envelopes[-1].timestamp_ns]
    meta = {
        "channel_names": channel_names,
        "time_range_ns": time_range_ns,
        "value_range": [vmin, vmax],
        "shape": [n_channels, t_total, line_length],
    }
    meta_path = output_dir / f"{stream_key}_waterfall.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
