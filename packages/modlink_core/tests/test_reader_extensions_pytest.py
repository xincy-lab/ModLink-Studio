from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from modlink_core.replay.reader import RecordedFrameRef, RecordingReader
from modlink_core.storage import (
    add_recording_marker,
    add_recording_segment,
    append_recording_frame,
    create_recording,
    finalize_recording,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reader(
    tmp_path: Path,
    descriptor_factory,
    frame_factory,
    *,
    timestamps_ns: tuple[int, ...] = (1_000, 2_000, 3_000),
    stream_key: str = "s1",
    finalize: bool = False,
) -> tuple[RecordingReader, str]:
    descriptor = descriptor_factory(
        payload_type="signal",
        stream_key=stream_key,
        chunk_size=2,
        channel_names=("ch0", "ch1"),
    )
    recording_id = create_recording(tmp_path, {descriptor.stream_id: descriptor})
    for i, ts in enumerate(timestamps_ns, start=1):
        append_recording_frame(
            tmp_path,
            recording_id,
            frame_factory(descriptor, timestamp_ns=ts, seq=i),
            frame_index=i,
        )
    if finalize:
        finalize_recording(
            tmp_path,
            recording_id,
            started_at_ns=timestamps_ns[0],
            stopped_at_ns=timestamps_ns[-1],
            status="completed",
            frame_counts_by_stream={descriptor.stream_id: len(timestamps_ns)},
        )
    reader = RecordingReader(tmp_path / "recordings" / recording_id)
    return reader, descriptor.stream_id


# ---------------------------------------------------------------------------
# frames_in_range
# ---------------------------------------------------------------------------


def test_frames_in_range_basic(tmp_path, descriptor_factory, frame_factory) -> None:
    reader, sid = _make_reader(
        tmp_path, descriptor_factory, frame_factory, timestamps_ns=(1_000, 2_000, 3_000)
    )
    # half-open relative [0, 2000) — should include absolute 1000 and 2000, NOT 3000
    result = reader.frames_in_range(sid, 0, 2_000)
    assert len(result) == 2
    assert all(isinstance(r, RecordedFrameRef) for r in result)
    assert result[0].timestamp_ns == 1_000
    assert result[1].timestamp_ns == 2_000


def test_frames_in_range_empty_stream(tmp_path, descriptor_factory, frame_factory) -> None:
    reader, _ = _make_reader(tmp_path, descriptor_factory, frame_factory)
    result = reader.frames_in_range("nonexistent_stream_id", 0, 999_999)
    assert result == ()


def test_frames_in_range_no_match(tmp_path, descriptor_factory, frame_factory) -> None:
    reader, sid = _make_reader(
        tmp_path, descriptor_factory, frame_factory, timestamps_ns=(1_000, 2_000)
    )
    result = reader.frames_in_range(sid, 9_000, 9_999)
    assert result == ()


# ---------------------------------------------------------------------------
# markers_in_range
# ---------------------------------------------------------------------------


def test_markers_in_range(tmp_path, descriptor_factory, frame_factory) -> None:
    descriptor = descriptor_factory(payload_type="signal", stream_key="m1", chunk_size=2)
    recording_id = create_recording(tmp_path, {descriptor.stream_id: descriptor})
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(descriptor, timestamp_ns=1_000, seq=1),
        frame_index=1,
    )
    # Markers stored as absolute ns; reader normalises relative to start_ns (1_000)
    add_recording_marker(tmp_path, recording_id, 1_500, "mid")
    add_recording_marker(tmp_path, recording_id, 2_000, "end")
    add_recording_marker(tmp_path, recording_id, 3_000, "after")

    reader = RecordingReader(tmp_path / "recordings" / recording_id)
    # After normalisation: mid→500, end→1000, after→2000
    result = reader.markers_in_range(0, 1_000)
    assert len(result) == 1
    assert result[0].label == "mid"
    assert result[0].timestamp_ns == 500


# ---------------------------------------------------------------------------
# overlapping_segments
# ---------------------------------------------------------------------------


def test_overlapping_segments_partial(tmp_path, descriptor_factory, frame_factory) -> None:
    descriptor = descriptor_factory(payload_type="signal", stream_key="seg1", chunk_size=2)
    recording_id = create_recording(tmp_path, {descriptor.stream_id: descriptor})
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(descriptor, timestamp_ns=1_000, seq=1),
        frame_index=1,
    )
    # Segment [500, 1500] absolute → normalised to [0, 500] (start_ns=1000 → 500-1000=-500→0, 1500-1000=500)
    # Actually: start_ns=500 → max(0, 500-1000)=0, end_ns=1500 → max(0,1500-1000)=500
    add_recording_segment(tmp_path, recording_id, 500, 1_500, "partial")

    reader = RecordingReader(tmp_path / "recordings" / recording_id)
    # Normalised segment: [0, 500]. Query [0, 500): 0 < 500 AND 500 > 0 → overlaps
    result = reader.overlapping_segments(0, 500)
    assert len(result) == 1
    assert result[0].label == "partial"
    # Timestamps are kept as-is (not clipped)
    assert result[0].start_ns == 0
    assert result[0].end_ns == 500


def test_overlapping_segments_outside(tmp_path, descriptor_factory, frame_factory) -> None:
    descriptor = descriptor_factory(payload_type="signal", stream_key="seg2", chunk_size=2)
    recording_id = create_recording(tmp_path, {descriptor.stream_id: descriptor})
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(descriptor, timestamp_ns=1_000, seq=1),
        frame_index=1,
    )
    # Segment [3000, 4000] absolute → normalised [2000, 3000]
    add_recording_segment(tmp_path, recording_id, 3_000, 4_000, "outside")

    reader = RecordingReader(tmp_path / "recordings" / recording_id)
    # Query [0, 1000): segment [2000, 3000] does NOT overlap
    result = reader.overlapping_segments(0, 1_000)
    assert result == ()


# ---------------------------------------------------------------------------
# stream_value_range
# ---------------------------------------------------------------------------


def test_stream_value_range_cache(tmp_path, descriptor_factory, frame_factory) -> None:
    reader, sid = _make_reader(
        tmp_path, descriptor_factory, frame_factory, timestamps_ns=(1_000, 2_000, 3_000)
    )
    call_count = 0
    original_load = reader.load_frame

    def counting_load(ref: RecordedFrameRef):
        nonlocal call_count
        call_count += 1
        return original_load(ref)

    with patch.object(reader, "load_frame", side_effect=counting_load):
        result1 = reader.stream_value_range(sid)
        calls_after_first = call_count
        result2 = reader.stream_value_range(sid)
        calls_after_second = call_count

    assert result1 is not None
    assert result1 == result2
    # Second call must not trigger any additional load_frame calls
    assert calls_after_second == calls_after_first


def test_stream_value_range_no_frames(tmp_path, descriptor_factory, frame_factory) -> None:
    # Build a reader with one stream, then query a nonexistent stream
    reader, _ = _make_reader(tmp_path, descriptor_factory, frame_factory)
    result = reader.stream_value_range("no_such_stream")
    assert result is None


# ---------------------------------------------------------------------------
# New properties
# ---------------------------------------------------------------------------


def test_new_properties_present(tmp_path, descriptor_factory, frame_factory) -> None:
    reader, sid = _make_reader(
        tmp_path,
        descriptor_factory,
        frame_factory,
        timestamps_ns=(1_000, 2_000, 3_000),
        finalize=True,
    )
    # Properties exist and return expected types / values
    assert reader.started_at_ns == 1_000
    assert reader.stopped_at_ns == 3_000
    assert reader.status == "completed"
    counts = reader.frame_counts_by_stream
    assert isinstance(counts, dict)
    assert counts[sid] == 3


def test_new_properties_without_finalize(tmp_path, descriptor_factory, frame_factory) -> None:
    reader, sid = _make_reader(
        tmp_path,
        descriptor_factory,
        frame_factory,
        timestamps_ns=(1_000, 2_000),
        finalize=False,
    )
    assert reader.started_at_ns is None
    assert reader.stopped_at_ns is None
    assert reader.status is None
    # Falls back to computing from _frames_by_stream
    counts = reader.frame_counts_by_stream
    assert counts[sid] == 2
