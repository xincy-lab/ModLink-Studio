from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ExportMode(Enum):
    SINGLE = "single"  # A: one recording, all streams
    MULTI = "multi"  # B: multiple recordings merged
    TIMESLICE = "timeslice"  # C: one recording, time range
    CROSS_STREAM = "cross_stream"  # D: one stream_key across recordings


# Valid format_id values per payload type:
# signal:  "signal_csv" | "signal_npz"
# raster:  "raster_waterfall_png" | "raster_waterfall_segmented_zip" | "raster_npz"
# field:   "field_npz" | "field_mp4" | "field_png_zip"
# video:   "video_mp4" | "video_png_zip"
VALID_FORMAT_IDS = frozenset(
    {
        "signal_csv",
        "signal_npz",
        "raster_waterfall_png",
        "raster_waterfall_segmented_zip",
        "raster_npz",
        "field_npz",
        "field_mp4",
        "field_png_zip",
        "video_mp4",
        "video_png_zip",
    }
)


@dataclass(frozen=True)
class StreamSelection:
    stream_id: str
    format_id: str  # must be one of VALID_FORMAT_IDS

    def __post_init__(self) -> None:
        if not self.stream_id:
            raise ValueError("stream_id must not be empty")
        if self.format_id not in VALID_FORMAT_IDS:
            raise ValueError(
                f"format_id {self.format_id!r} is not valid; choose from {sorted(VALID_FORMAT_IDS)}"
            )


@dataclass(frozen=True)
class ExportRequest:
    mode: ExportMode
    recording_ids: tuple[str, ...]
    streams: tuple[StreamSelection, ...]
    time_range_ns: tuple[int, int] | None = None
    include_annotations: bool = True
    include_recording_metadata: bool = True
    include_raw: bool = False
    package_as_zip: bool = False
    concat_streams: bool = False  # D mode only: concat across recordings

    def __post_init__(self) -> None:
        if not self.recording_ids:
            raise ValueError("recording_ids must not be empty")
        if not self.streams:
            raise ValueError("streams must not be empty")
        if self.mode == ExportMode.SINGLE and len(self.recording_ids) != 1:
            raise ValueError("SINGLE mode requires exactly 1 recording_id")
        if self.mode == ExportMode.TIMESLICE:
            if len(self.recording_ids) != 1:
                raise ValueError("TIMESLICE mode requires exactly 1 recording_id")
            if self.time_range_ns is None:
                raise ValueError("TIMESLICE mode requires time_range_ns")
        if self.mode == ExportMode.MULTI and len(self.recording_ids) < 2:
            raise ValueError("MULTI mode requires at least 2 recording_ids")
        if self.time_range_ns is not None:
            start, end = self.time_range_ns
            if start >= end:
                raise ValueError(f"time_range_ns start ({start}) must be < end ({end})")
