from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path

from modlink_core.models import ReplayMarker, ReplaySegment


def write_markers_csv(markers: Sequence[ReplayMarker], output_path: Path) -> None:
    """Write markers to CSV. Always creates file, even if markers is empty (header only)."""
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp_ns", "label"])
        for marker in markers:
            writer.writerow([marker.timestamp_ns, marker.label])


def write_segments_csv(segments: Sequence[ReplaySegment], output_path: Path) -> None:
    """Write segments to CSV. Always creates file, even if segments is empty (header only)."""
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["start_ns", "end_ns", "label"])
        for segment in segments:
            writer.writerow([segment.start_ns, segment.end_ns, segment.label])
