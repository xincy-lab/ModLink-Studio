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
from ..format.recording_metadata import write_recording_metadata_json
from ..format.signal_csv import write_signal_csv
from ..format.signal_npz import write_signal_npz
from ..format.video_mp4 import write_video_mp4
from ..format.video_png_zip import write_video_png_zip
from ..package_writer import ExportPackageWriter
from ..store import RecordingStore


def export_multi_recording(
    request: ExportRequest,
    store: RecordingStore,
    output_root: Path,
    progress_fn: Callable[[str], None] | None = None,
) -> Path:
    """Export multiple recordings into a single bundle with per-recording subdirectories.

    Returns the final bundle path.
    """
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    bundle_name = f"multi_export_{timestamp}"

    with ExportPackageWriter(output_root / bundle_name) as pkg:
        recordings_dir = pkg.root / "recordings"
        recordings_dir.mkdir()

        for recording_id in request.recording_ids:
            reader = store.open(recording_id)
            descriptors = reader.descriptors()

            rec_dir = recordings_dir / recording_id
            streams_dir = rec_dir / "streams"
            streams_dir.mkdir(parents=True)

            for sel in request.streams:
                frame_refs = reader.frames_in_range(sel.stream_id, 0, 2**63)

                # Skip silently if stream not in this recording
                if not frame_refs and sel.stream_id not in descriptors:
                    continue

                descriptor = descriptors.get(sel.stream_id)
                stream_key = descriptor.stream_key if descriptor is not None else sel.stream_id

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
                else:
                    raise ValueError(f"unknown format_id {sel.format_id!r}")

                if progress_fn is not None:
                    progress_fn(f"{recording_id}/{sel.stream_id}")

            if request.include_annotations:
                annotations_dir = rec_dir / "annotations"
                annotations_dir.mkdir()
                write_markers_csv(reader.markers(), annotations_dir / "markers.csv")
                write_segments_csv(reader.segments(), annotations_dir / "segments.csv")

            if request.include_recording_metadata:
                write_recording_metadata_json(reader, rec_dir / "recording_metadata.json")

        manifest = {
            "bundle_name": bundle_name,
            "mode": "multi",
            "recording_ids": list(request.recording_ids),
            "created_at": timestamp,
        }
        (pkg.root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        readme_lines = [
            f"# Export Bundle: {bundle_name}",
            "",
            "## Contents",
            "",
            "- **Mode**: multi",
            f"- **Recording(s)**: {', '.join(request.recording_ids)}",
            "",
            "## Directory Structure",
            "",
            "```",
            f"{bundle_name}/",
            "├── manifest.json",
            "├── README.md",
            "└── recordings/",
        ]
        for rec_id in request.recording_ids:
            readme_lines.append(f"    └── {rec_id}/")
            readme_lines.append("        ├── streams/")
            if request.include_annotations:
                readme_lines.append("        ├── annotations/")
            if request.include_recording_metadata:
                readme_lines.append("        └── recording_metadata.json")
        readme_lines.append("```")
        readme_lines.append("")
        readme_lines.append("---")
        readme_lines.append("*Generated by ModLink Studio export system*")
        readme_lines.append("")

        (pkg.root / "README.md").write_text("\n".join(readme_lines), encoding="utf-8")

    return pkg.final_path
