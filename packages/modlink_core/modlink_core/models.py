from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DriverSnapshot:
    driver_id: str
    display_name: str
    supported_providers: tuple[str, ...]
    is_running: bool
    is_connected: bool
    is_streaming: bool


@dataclass(frozen=True, slots=True)
class RecordingSnapshot:
    state: str
    is_started: bool
    is_recording: bool
    root_dir: str


@dataclass(frozen=True, slots=True)
class RecordingStartSummary:
    recording_id: str
    recording_path: str
    started_at_ns: int


@dataclass(frozen=True, slots=True)
class RecordingStopSummary:
    recording_id: str
    recording_path: str
    started_at_ns: int
    stopped_at_ns: int
    status: str
    frame_counts_by_stream: dict[str, int]


@dataclass(frozen=True, slots=True)
class ReplaySnapshot:
    state: str
    is_started: bool
    recording_id: str | None
    recording_path: str | None
    position_ns: int
    duration_ns: int
    speed_multiplier: float


@dataclass(frozen=True, slots=True)
class ReplayRecordingSummary:
    recording_id: str
    recording_label: str | None
    recording_path: str
    stream_ids: tuple[str, ...]
    session_name: str | None = None
    experiment_name: str | None = None
    started_at_ns: int | None = None
    duration_ns: int | None = None
    status: str | None = None
    total_frames: int | None = None


@dataclass(frozen=True, slots=True)
class ReplayMarker:
    timestamp_ns: int
    label: str | None


@dataclass(frozen=True, slots=True)
class ReplaySegment:
    start_ns: int
    end_ns: int
    label: str | None


@dataclass(frozen=True, slots=True)
class ExportJobSnapshot:
    job_id: str
    recording_id: str
    state: str
    progress: float
    output_path: str | None
    error: str | None
    request_summary: str = ""
