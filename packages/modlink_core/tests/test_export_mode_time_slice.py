from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from modlink_core.models import ReplayMarker, ReplaySegment
from modlink_core.replay.export_modes.time_slice import export_time_slice
from modlink_core.replay.export_request import ExportMode, ExportRequest, StreamSelection
from modlink_core.replay.reader import RecordedFrameRef
from modlink_sdk import FrameEnvelope, StreamDescriptor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _signal_descriptor(stream_key: str = "demo") -> StreamDescriptor:
    return StreamDescriptor(
        device_id="demo.01",
        stream_key=stream_key,
        payload_type="signal",
        nominal_sample_rate_hz=1000.0,  # 1 sample per ms
        chunk_size=1,
        channel_names=("ch0",),
        display_name=None,
        metadata={},
    )


def _frame_ref(stream_id: str, timestamp_ns: int, frame_index: int = 0) -> RecordedFrameRef:
    return RecordedFrameRef(
        stream_id=stream_id,
        frame_index=frame_index,
        timestamp_ns=timestamp_ns,
        seq=frame_index,
        file_name=f"frame_{frame_index:04d}.npy",
        relative_timestamp_ns=timestamp_ns,
    )


def _frame_envelope(stream_key: str, timestamp_ns: int) -> FrameEnvelope:
    return FrameEnvelope(
        device_id="demo.01",
        stream_key=stream_key,
        timestamp_ns=timestamp_ns,
        data=np.array([[float(timestamp_ns)]], dtype=np.float32),  # shape (1, 1)
        seq=0,
    )


def _make_request(
    recording_id: str = "rec_001",
    stream_id: str = "sig_stream",
    format_id: str = "signal_csv",
    time_range_ns: tuple[int, int] = (2000, 7000),
    include_annotations: bool = False,
    include_recording_metadata: bool = False,
) -> ExportRequest:
    return ExportRequest(
        mode=ExportMode.TIMESLICE,
        recording_ids=(recording_id,),
        streams=(StreamSelection(stream_id=stream_id, format_id=format_id),),
        time_range_ns=time_range_ns,
        include_annotations=include_annotations,
        include_recording_metadata=include_recording_metadata,
    )


def _make_reader_with_frames(
    stream_id: str,
    stream_key: str,
    all_timestamps: list[int],
    markers: list[ReplayMarker] | None = None,
    segments: list[ReplaySegment] | None = None,
    recording_id: str = "rec_001",
) -> MagicMock:
    """Reader whose frames_in_range/markers_in_range/overlapping_segments filter correctly."""
    desc = _signal_descriptor(stream_key)
    all_refs = [_frame_ref(stream_id, ts, i) for i, ts in enumerate(all_timestamps)]
    all_markers = markers or []
    all_segments = segments or []

    reader = MagicMock()
    reader.recording_id = recording_id
    reader._manifest = {"recording_id": recording_id}
    reader.descriptors.return_value = {stream_id: desc}
    reader.descriptor.return_value = desc

    # Implement half-open [start, end) filtering
    def frames_in_range(sid: str, start: int, end: int) -> tuple[RecordedFrameRef, ...]:
        return tuple(r for r in all_refs if start <= r.timestamp_ns < end)

    def markers_in_range(start: int, end: int) -> tuple[ReplayMarker, ...]:
        return tuple(m for m in all_markers if start <= m.timestamp_ns < end)

    def overlapping_segments(start: int, end: int) -> tuple[ReplaySegment, ...]:
        return tuple(s for s in all_segments if s.start_ns < end and s.end_ns > start)

    reader.frames_in_range.side_effect = frames_in_range
    reader.markers_in_range.side_effect = markers_in_range
    reader.overlapping_segments.side_effect = overlapping_segments

    def load_frame(ref: RecordedFrameRef) -> FrameEnvelope:
        return _frame_envelope(stream_key, ref.timestamp_ns)

    reader.load_frame.side_effect = load_frame
    reader.markers.return_value = tuple(all_markers)
    reader.segments.return_value = tuple(all_segments)
    reader.started_at_ns = min(all_timestamps) if all_timestamps else 0
    reader.stopped_at_ns = max(all_timestamps) if all_timestamps else 0
    reader.status = "completed"
    reader.frame_counts_by_stream = {stream_id: len(all_refs)}
    return reader


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_frames_filtered_by_range(tmp_path: Path) -> None:
    """10 frames at [0, 1000, ..., 9000]; slice [2000, 7000) → 5 frames in CSV."""
    stream_id = "sig_stream"
    stream_key = "demo"
    timestamps = list(range(0, 10_000, 1000))  # 0, 1000, ..., 9000

    reader = _make_reader_with_frames(stream_id, stream_key, timestamps)
    request = _make_request(time_range_ns=(2000, 7000))

    bundle_path = export_time_slice(request, reader, tmp_path)

    csv_path = bundle_path / "streams" / f"{stream_key}.csv"
    assert csv_path.is_file()

    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Frames at 2000, 3000, 4000, 5000, 6000 → 5 rows
    assert len(rows) == 5
    ts_values = [int(r["timestamp_ns"]) for r in rows]
    assert ts_values[0] == 2000
    assert ts_values[-1] == 6000


def test_half_open_boundary(tmp_path: Path) -> None:
    """Frame at exactly end_ns must NOT be included."""
    stream_id = "sig_stream"
    stream_key = "demo"
    # Frames at 1000, 2000, 3000 — slice [1000, 3000) → 1000 and 2000 only
    timestamps = [1000, 2000, 3000]

    reader = _make_reader_with_frames(stream_id, stream_key, timestamps)
    request = _make_request(time_range_ns=(1000, 3000))

    bundle_path = export_time_slice(request, reader, tmp_path)

    csv_path = bundle_path / "streams" / f"{stream_key}.csv"
    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    ts_values = [int(r["timestamp_ns"]) for r in rows]
    assert 3000 not in ts_values
    assert 1000 in ts_values
    assert 2000 in ts_values
    assert len(rows) == 2


def test_markers_filtered(tmp_path: Path) -> None:
    """3 markers at [1000, 3000, 8000]; slice [2000, 7000) → markers.csv has 1 data row (3000)."""
    stream_id = "sig_stream"
    stream_key = "demo"
    timestamps = list(range(0, 10_000, 1000))
    markers = [
        ReplayMarker(timestamp_ns=1000, label="before"),
        ReplayMarker(timestamp_ns=3000, label="inside"),
        ReplayMarker(timestamp_ns=8000, label="after"),
    ]

    reader = _make_reader_with_frames(stream_id, stream_key, timestamps, markers=markers)
    request = _make_request(time_range_ns=(2000, 7000), include_annotations=True)

    bundle_path = export_time_slice(request, reader, tmp_path)

    markers_csv = bundle_path / "annotations" / "markers.csv"
    assert markers_csv.is_file()

    with markers_csv.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    assert int(rows[0]["timestamp_ns"]) == 3000
    assert rows[0]["label"] == "inside"


def test_segments_original_timestamps(tmp_path: Path) -> None:
    """Segment [500, 1500] overlapping [1000, 2000) → CSV has original timestamps [500, 1500]."""
    stream_id = "sig_stream"
    stream_key = "demo"
    timestamps = list(range(0, 3000, 500))
    segments = [
        ReplaySegment(start_ns=500, end_ns=1500, label="overlap"),
    ]

    reader = _make_reader_with_frames(stream_id, stream_key, timestamps, segments=segments)
    request = _make_request(time_range_ns=(1000, 2000), include_annotations=True)

    bundle_path = export_time_slice(request, reader, tmp_path)

    segments_csv = bundle_path / "annotations" / "segments.csv"
    assert segments_csv.is_file()

    with segments_csv.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    # Original timestamps preserved — NOT clipped to slice range
    assert int(rows[0]["start_ns"]) == 500
    assert int(rows[0]["end_ns"]) == 1500


def test_empty_range_produces_valid_bundle(tmp_path: Path) -> None:
    """Range with no frames → valid bundle with empty CSV (header only)."""
    stream_id = "sig_stream"
    stream_key = "demo"
    # All frames outside the slice range
    timestamps = [100, 200, 300]

    reader = _make_reader_with_frames(stream_id, stream_key, timestamps)
    # Slice [5000, 9000) — no frames fall in this range
    request = _make_request(time_range_ns=(5000, 9000))

    bundle_path = export_time_slice(request, reader, tmp_path)

    assert bundle_path.is_dir()
    assert (bundle_path / "manifest.json").is_file()
    assert (bundle_path / "README.md").is_file()

    csv_path = bundle_path / "streams" / f"{stream_key}.csv"
    assert csv_path.is_file()

    content = csv_path.read_bytes()
    # Header must be present; no data rows
    lines = [ln for ln in content.split(b"\r\n") if ln]
    assert len(lines) == 1  # header only


def test_bundle_has_manifest(tmp_path: Path) -> None:
    """manifest.json exists with time_range_ns key and correct mode."""
    stream_id = "sig_stream"
    stream_key = "demo"
    timestamps = [1000, 2000, 3000]

    reader = _make_reader_with_frames(stream_id, stream_key, timestamps)
    request = _make_request(time_range_ns=(1000, 3000))

    bundle_path = export_time_slice(request, reader, tmp_path)

    manifest_path = bundle_path / "manifest.json"
    assert manifest_path.is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["mode"] == "timeslice"
    assert "time_range_ns" in manifest
    assert manifest["time_range_ns"] == [1000, 3000]
    assert manifest["recording_id"] == "rec_001"
    assert stream_id in manifest["streams"]
