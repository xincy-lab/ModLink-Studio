from __future__ import annotations

import json
from pathlib import Path

from ..reader import RecordingReader


def write_recording_metadata_json(reader: RecordingReader, output_path: Path) -> None:
    """Write recording metadata to JSON file."""
    started = reader.started_at_ns
    stopped = reader.stopped_at_ns
    duration = (stopped - started) if (started is not None and stopped is not None) else None

    streams: dict[str, dict] = {}
    for stream_id, desc in reader.descriptors().items():
        streams[stream_id] = {
            "device_id": desc.device_id,
            "stream_key": desc.stream_key,
            "payload_type": desc.payload_type.value
            if hasattr(desc.payload_type, "value")
            else str(desc.payload_type),
            "nominal_sample_rate_hz": desc.nominal_sample_rate_hz,
            "chunk_size": desc.chunk_size,
            "channel_names": list(desc.channel_names),
        }

    metadata = {
        "recording_id": reader.recording_id,
        "started_at_ns": started,
        "stopped_at_ns": stopped,
        "duration_ns": duration,
        "status": reader.status,
        "frame_counts_by_stream": reader.frame_counts_by_stream,
        "streams": streams,
    }

    output_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
