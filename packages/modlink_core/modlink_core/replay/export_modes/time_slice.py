from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from ..export_request import ExportRequest
from ..format.annotations import write_markers_csv, write_segments_csv
from ..format.field_mp4 import write_field_mp4
from ..format.field_npz import write_field_npz
from ..format.field_png_zip import write_field_png_zip
from ..format.raster_npz import write_raster_npz
from ..format.raster_png import write_raster_waterfall_png
from ..format.raster_png_segmented import write_raster_waterfall_segmented_zip
from ..format.readme import generate_readme
from ..format.recording_metadata import write_recording_metadata_json
from ..format.signal_csv import write_signal_csv
from ..format.signal_npz import write_signal_npz
from ..format.video_mp4 import write_video_mp4
from ..format.video_png_zip import write_video_png_zip
from ..package_writer import ExportPackageWriter
from ..reader import RecordingReader


def export_time_slice(
    request: ExportRequest,
    reader: RecordingReader,
    output_root: Path,
    progress_fn: Callable[[str], None] | None = None,
) -> Path:
    """Export a time slice of a single recording.

    request.time_range_ns must be set (validated by ExportRequest.__post_init__).
    Returns the final bundle path.
    """
    start_ns, end_ns = request.time_range_ns  # type: ignore[misc]
    recording_id = reader._manifest.get("recording_id", "unknown")
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    bundle_name = f"{recording_id}_{timestamp}_slice_export"

    with ExportPackageWriter(output_root / bundle_name) as pkg:
        streams_dir = pkg.root / "streams"
        streams_dir.mkdir()

        descriptors = reader.descriptors()
        stream_keys: list[str] = []

        for sel in request.streams:
            descriptor = descriptors[sel.stream_id]
            stream_key = descriptor.stream_key
            stream_keys.append(stream_key)

            frame_refs = reader.frames_in_range(sel.stream_id, start_ns, end_ns)

            if sel.format_id == "signal_csv":
                write_signal_csv(
                    reader, sel.stream_id, frame_refs, streams_dir / f"{stream_key}.csv"
                )
            elif sel.format_id == "signal_npz":
                write_signal_npz(
                    reader, sel.stream_id, frame_refs, streams_dir / f"{stream_key}.npz"
                )
            elif sel.format_id == "raster_waterfall_png":
                write_raster_waterfall_png(reader, sel.stream_id, frame_refs, streams_dir)
            elif sel.format_id == "raster_waterfall_segmented_zip":
                write_raster_waterfall_segmented_zip(
                    reader,
                    sel.stream_id,
                    frame_refs,
                    segment_chunks=100,
                    output_path=streams_dir / f"{stream_key}_segmented.zip",
                )
            elif sel.format_id == "raster_npz":
                write_raster_npz(
                    reader, sel.stream_id, frame_refs, streams_dir / f"{stream_key}.npz"
                )
            elif sel.format_id == "field_npz":
                write_field_npz(
                    reader, sel.stream_id, frame_refs, streams_dir / f"{stream_key}.npz"
                )
            elif sel.format_id == "field_mp4":
                write_field_mp4(reader, sel.stream_id, frame_refs, streams_dir)
            elif sel.format_id == "field_png_zip":
                write_field_png_zip(
                    reader, sel.stream_id, frame_refs, streams_dir / f"{stream_key}_frames.zip"
                )
            elif sel.format_id == "video_mp4":
                write_video_mp4(reader, sel.stream_id, frame_refs, streams_dir)
            elif sel.format_id == "video_png_zip":
                write_video_png_zip(
                    reader, sel.stream_id, frame_refs, streams_dir / f"{stream_key}_frames.zip"
                )

            if progress_fn is not None:
                progress_fn(sel.stream_id)

        if request.include_annotations:
            annotations_dir = pkg.root / "annotations"
            annotations_dir.mkdir()
            write_markers_csv(
                reader.markers_in_range(start_ns, end_ns), annotations_dir / "markers.csv"
            )
            write_segments_csv(
                reader.overlapping_segments(start_ns, end_ns), annotations_dir / "segments.csv"
            )

        if request.include_recording_metadata:
            write_recording_metadata_json(reader, pkg.root / "recording_metadata.json")

        manifest = {
            "bundle_name": bundle_name,
            "recording_id": recording_id,
            "mode": "timeslice",
            "time_range_ns": [start_ns, end_ns],
            "streams": [sel.stream_id for sel in request.streams],
            "created_at": timestamp,
        }
        (pkg.root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        readme = generate_readme(
            bundle_name=bundle_name,
            recording_ids=request.recording_ids,
            mode="timeslice",
            time_range_ns=request.time_range_ns,
            stream_keys=tuple(stream_keys),
            has_annotations=request.include_annotations,
            has_recording_metadata=request.include_recording_metadata,
        )
        (pkg.root / "README.md").write_text(readme, encoding="utf-8")

    return pkg.final_path
