"""End-to-end integration tests for all 4 export modes (A/B/C/D).

Each test builds a real recording (or set of recordings) via the storage helpers,
invokes the corresponding mode handler that ExportEngine dispatches to, and
verifies the resulting bundle structure.
"""

from __future__ import annotations

import csv
import json

import pytest

from modlink_core.replay.export_modes.cross import export_cross_recording_stream
from modlink_core.replay.export_modes.multi import export_multi_recording
from modlink_core.replay.export_modes.single import export_single_recording
from modlink_core.replay.export_modes.time_slice import export_time_slice
from modlink_core.replay.export_request import ExportMode, ExportRequest, StreamSelection
from modlink_core.replay.reader import RecordingReader
from modlink_core.replay.store import RecordingStore
from modlink_core.storage import (
    add_recording_marker,
    add_recording_segment,
    append_recording_frame,
    create_recording,
    finalize_recording,
)


@pytest.fixture
def mock_mp4_writer(monkeypatch):
    """Replace Mp4Writer.write with a no-op that creates an empty placeholder file.

    Both video_mp4 and field_mp4 import Mp4Writer from the same module, so a
    single class-level patch covers both paths without requiring real ffmpeg.
    """

    def fake_write(frames, fps, output_path):  # noqa: ARG001 - signature must match
        output_path.write_bytes(b"")

    monkeypatch.setattr(
        "modlink_core.replay.format.mp4_writer.Mp4Writer.write",
        fake_write,
    )


# ---------------------------------------------------------------------------
# Mode A: SINGLE — one recording, all streams + annotations + metadata
# ---------------------------------------------------------------------------


def test_single_mode_full_export(tmp_path, descriptor_factory, frame_factory, mock_mp4_writer):
    """One recording with signal+raster+field+video streams, 2 markers, 1 segment."""
    signal_desc = descriptor_factory(
        payload_type="signal",
        stream_key="signal",
        chunk_size=4,
        channel_names=("ch0", "ch1"),
    )
    raster_desc = descriptor_factory(
        payload_type="raster",
        stream_key="raster",
        chunk_size=2,
    )
    field_desc = descriptor_factory(
        payload_type="field",
        stream_key="field",
        chunk_size=2,
        nominal_sample_rate_hz=10.0,
    )
    video_desc = descriptor_factory(
        payload_type="video",
        stream_key="video",
        chunk_size=2,
        nominal_sample_rate_hz=10.0,
    )

    descriptors = {
        signal_desc.stream_id: signal_desc,
        raster_desc.stream_id: raster_desc,
        field_desc.stream_id: field_desc,
        video_desc.stream_id: video_desc,
    }
    recording_id = create_recording(tmp_path, descriptors, recording_label="full")

    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(signal_desc, timestamp_ns=0),
        frame_index=1,
    )
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(raster_desc, timestamp_ns=0),
        frame_index=1,
    )
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(field_desc, timestamp_ns=0),
        frame_index=1,
    )
    # video_mp4 requires C in {1, 3, 4}; default channel_count is 2, so override to 3 (RGB).
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(video_desc, timestamp_ns=0, channel_count=3),
        frame_index=1,
    )

    add_recording_marker(tmp_path, recording_id, 100_000_000, "m1")
    add_recording_marker(tmp_path, recording_id, 500_000_000, "m2")
    add_recording_segment(tmp_path, recording_id, 0, 1_000_000_000, "seg1")

    finalize_recording(
        tmp_path,
        recording_id,
        started_at_ns=0,
        stopped_at_ns=1_000_000_000,
        status="completed",
        frame_counts_by_stream={
            signal_desc.stream_id: 1,
            raster_desc.stream_id: 1,
            field_desc.stream_id: 1,
            video_desc.stream_id: 1,
        },
    )

    reader = RecordingReader(tmp_path / "recordings" / recording_id)
    output_root = tmp_path / "exports"
    output_root.mkdir()

    request = ExportRequest(
        mode=ExportMode.SINGLE,
        recording_ids=(recording_id,),
        streams=(
            StreamSelection(stream_id=signal_desc.stream_id, format_id="signal_csv"),
            StreamSelection(stream_id=raster_desc.stream_id, format_id="raster_npz"),
            StreamSelection(stream_id=field_desc.stream_id, format_id="field_npz"),
            StreamSelection(stream_id=video_desc.stream_id, format_id="video_mp4"),
        ),
        include_annotations=True,
        include_recording_metadata=True,
    )

    bundle_path = export_single_recording(request, reader, output_root)

    # Bundle root + top-level files
    assert bundle_path.is_dir()
    assert (bundle_path / "manifest.json").is_file()
    assert (bundle_path / "README.md").is_file()
    assert (bundle_path / "streams").is_dir()

    # All four payload-type stream outputs are present.
    streams_dir = bundle_path / "streams"
    assert (streams_dir / "signal.csv").is_file()
    assert (streams_dir / "raster.npz").is_file()
    assert (streams_dir / "field.npz").is_file()
    assert (streams_dir / "video.mp4").is_file()  # written by mocked Mp4Writer
    assert (streams_dir / "video.frame_timestamps.csv").is_file()

    # Annotations and per-recording metadata.
    assert (bundle_path / "annotations" / "markers.csv").is_file()
    assert (bundle_path / "annotations" / "segments.csv").is_file()
    assert (bundle_path / "recording_metadata.json").is_file()

    # Manifest + README content sanity checks.
    manifest = json.loads((bundle_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "single"
    assert manifest["recording_id"] == recording_id
    assert len(manifest["streams"]) == 4

    readme_text = (bundle_path / "README.md").read_text(encoding="utf-8")
    assert bundle_path.name in readme_text
    assert "single" in readme_text.lower()

    # Annotations rows match what we wrote.
    with (bundle_path / "annotations" / "markers.csv").open(newline="", encoding="utf-8") as f:
        marker_rows = list(csv.DictReader(f))
    assert len(marker_rows) == 2

    with (bundle_path / "annotations" / "segments.csv").open(newline="", encoding="utf-8") as f:
        segment_rows = list(csv.DictReader(f))
    assert len(segment_rows) == 1

    # No leftover .tmp_* directories from atomic-write staging.
    leftover = [p.name for p in output_root.iterdir() if p.name.startswith(".tmp_")]
    assert leftover == [], f"leftover tmp dirs: {leftover}"


# ---------------------------------------------------------------------------
# Mode B: MULTI — multiple recordings into per-recording subdirs
# ---------------------------------------------------------------------------


def test_multi_mode_merged_export(tmp_path, descriptor_factory, frame_factory):
    """2 recordings, each with the same signal stream → recordings/<id>/streams/<key>.csv."""
    descriptor = descriptor_factory(
        payload_type="signal",
        stream_key="eeg",
        chunk_size=4,
        channel_names=("ch0", "ch1"),
    )

    recording_ids: list[str] = []
    for i in range(2):
        rec_id = create_recording(
            tmp_path,
            {descriptor.stream_id: descriptor},
            recording_label=f"rec_{i}",
        )
        append_recording_frame(
            tmp_path,
            rec_id,
            frame_factory(descriptor, timestamp_ns=i * 1_000_000_000),
            frame_index=1,
        )
        add_recording_marker(tmp_path, rec_id, i * 1_000_000_000 + 50_000_000, f"m_{i}")
        finalize_recording(
            tmp_path,
            rec_id,
            started_at_ns=i * 1_000_000_000,
            stopped_at_ns=(i + 1) * 1_000_000_000,
            status="completed",
            frame_counts_by_stream={descriptor.stream_id: 1},
        )
        recording_ids.append(rec_id)

    store = RecordingStore(tmp_path)
    output_root = tmp_path / "exports"
    output_root.mkdir()

    request = ExportRequest(
        mode=ExportMode.MULTI,
        recording_ids=tuple(recording_ids),
        streams=(StreamSelection(stream_id=descriptor.stream_id, format_id="signal_csv"),),
        include_annotations=True,
        include_recording_metadata=True,
    )

    bundle_path = export_multi_recording(request, store, output_root)

    assert bundle_path.is_dir()
    assert (bundle_path / "manifest.json").is_file()
    assert (bundle_path / "README.md").is_file()
    assert (bundle_path / "recordings").is_dir()

    for rec_id in recording_ids:
        rec_dir = bundle_path / "recordings" / rec_id
        assert rec_dir.is_dir()
        assert (rec_dir / "streams" / "eeg.csv").is_file()
        assert (rec_dir / "annotations" / "markers.csv").is_file()
        assert (rec_dir / "annotations" / "segments.csv").is_file()
        assert (rec_dir / "recording_metadata.json").is_file()

    manifest = json.loads((bundle_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "multi"
    assert set(manifest["recording_ids"]) == set(recording_ids)

    readme_text = (bundle_path / "README.md").read_text(encoding="utf-8")
    assert bundle_path.name in readme_text
    assert "multi" in readme_text.lower()

    leftover = [p.name for p in output_root.iterdir() if p.name.startswith(".tmp_")]
    assert leftover == [], f"leftover tmp dirs: {leftover}"


# ---------------------------------------------------------------------------
# Mode C: TIMESLICE — single recording, time range filters frames + markers
# ---------------------------------------------------------------------------


def test_timeslice_mode_with_marker_range(tmp_path, descriptor_factory, frame_factory):
    """5 frames at 0/100/200/300/400 ms; slice [100M, 300M) → 2 frames + 1 marker."""
    descriptor = descriptor_factory(
        payload_type="signal",
        stream_key="eeg",
        chunk_size=1,
        nominal_sample_rate_hz=10.0,
        channel_names=("ch0",),
    )
    recording_id = create_recording(tmp_path, {descriptor.stream_id: descriptor})

    # Recording begins at t=0 so absolute frame timestamps == reader-relative
    # timestamps. This keeps the slice range consistent for both
    # frames_in_range (absolute) and markers_in_range (relative).
    for i in range(5):
        append_recording_frame(
            tmp_path,
            recording_id,
            frame_factory(
                descriptor,
                timestamp_ns=i * 100_000_000,
                chunk_size=1,
                channel_count=1,
            ),
            frame_index=i + 1,
        )

    add_recording_marker(tmp_path, recording_id, 50_000_000, "before")
    add_recording_marker(tmp_path, recording_id, 200_000_000, "inside")
    add_recording_marker(tmp_path, recording_id, 350_000_000, "after")
    add_recording_segment(tmp_path, recording_id, 100_000_000, 300_000_000, "seg")

    finalize_recording(
        tmp_path,
        recording_id,
        started_at_ns=0,
        stopped_at_ns=400_000_000,
        status="completed",
        frame_counts_by_stream={descriptor.stream_id: 5},
    )

    reader = RecordingReader(tmp_path / "recordings" / recording_id)
    output_root = tmp_path / "exports"
    output_root.mkdir()

    request = ExportRequest(
        mode=ExportMode.TIMESLICE,
        recording_ids=(recording_id,),
        streams=(StreamSelection(stream_id=descriptor.stream_id, format_id="signal_csv"),),
        time_range_ns=(100_000_000, 300_000_000),
        include_annotations=True,
        include_recording_metadata=True,
    )

    bundle_path = export_time_slice(request, reader, output_root)

    assert bundle_path.is_dir()
    assert (bundle_path / "manifest.json").is_file()
    assert (bundle_path / "README.md").is_file()

    csv_path = bundle_path / "streams" / "eeg.csv"
    assert csv_path.is_file()

    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # Frames at 100M and 200M fall in [100M, 300M); each carries 1 sample → 2 rows.
    assert len(rows) == 2

    # Only the "inside" marker (at 200M) falls in the slice range.
    markers_csv = bundle_path / "annotations" / "markers.csv"
    assert markers_csv.is_file()
    with markers_csv.open(newline="", encoding="utf-8") as f:
        marker_rows = list(csv.DictReader(f))
    assert len(marker_rows) == 1
    assert marker_rows[0]["label"] == "inside"

    # The single segment overlaps the slice range.
    segments_csv = bundle_path / "annotations" / "segments.csv"
    assert segments_csv.is_file()
    with segments_csv.open(newline="", encoding="utf-8") as f:
        segment_rows = list(csv.DictReader(f))
    assert len(segment_rows) == 1

    manifest = json.loads((bundle_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "timeslice"
    assert manifest["time_range_ns"] == [100_000_000, 300_000_000]
    assert manifest["recording_id"] == recording_id

    assert (bundle_path / "recording_metadata.json").is_file()

    leftover = [p.name for p in output_root.iterdir() if p.name.startswith(".tmp_")]
    assert leftover == [], f"leftover tmp dirs: {leftover}"


# ---------------------------------------------------------------------------
# Mode D: CROSS_STREAM — one stream across multiple recordings, concat=True
# ---------------------------------------------------------------------------


def test_cross_mode_with_concat(tmp_path, descriptor_factory, frame_factory):
    """2 recordings, same signal stream_key, concat=True → merged CSV with recording_id col."""
    descriptor = descriptor_factory(
        payload_type="signal",
        stream_key="eeg",
        chunk_size=4,
        channel_names=("ch0", "ch1"),
        nominal_sample_rate_hz=100.0,
    )

    recording_ids: list[str] = []
    for i in range(2):
        rec_id = create_recording(tmp_path, {descriptor.stream_id: descriptor})
        append_recording_frame(
            tmp_path,
            rec_id,
            frame_factory(descriptor, timestamp_ns=i * 1_000_000_000, chunk_size=4),
            frame_index=1,
        )
        finalize_recording(
            tmp_path,
            rec_id,
            started_at_ns=i * 1_000_000_000,
            stopped_at_ns=(i + 1) * 1_000_000_000,
            status="completed",
            frame_counts_by_stream={descriptor.stream_id: 1},
        )
        recording_ids.append(rec_id)

    store = RecordingStore(tmp_path)
    output_root = tmp_path / "exports"
    output_root.mkdir()

    request = ExportRequest(
        mode=ExportMode.CROSS_STREAM,
        recording_ids=tuple(recording_ids),
        streams=(StreamSelection(stream_id=descriptor.stream_id, format_id="signal_csv"),),
        concat_streams=True,
    )

    bundle_path = export_cross_recording_stream(request, store, output_root)

    assert bundle_path.is_dir()
    assert (bundle_path / "manifest.json").is_file()
    assert (bundle_path / "README.md").is_file()

    # Bundle filenames sanitize the stream_id so platforms with reserved chars
    # (e.g. ':' on Windows) accept the path. The manifest still records the
    # original stream_key for downstream tooling.
    from modlink_core.storage._internal.ids import safe_path_component

    safe_stream = safe_path_component(descriptor.stream_id)
    concat_csv = bundle_path / "streams" / f"{safe_stream}_concat.csv"
    assert concat_csv.is_file()

    with concat_csv.open(newline="", encoding="utf-8") as f:
        reader_csv = csv.reader(f)
        header = next(reader_csv)
        data_rows = list(reader_csv)

    assert header[0] == "recording_id"
    assert header[1] == "timestamp_ns"
    # 2 recordings × 1 frame each × 4 samples per frame = 8 rows
    assert len(data_rows) == 2 * 4

    rec_ids_in_csv = {row[0] for row in data_rows}
    assert rec_ids_in_csv == set(recording_ids)

    manifest = json.loads((bundle_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "cross_stream"
    assert manifest["concat"] is True
    assert set(manifest["recording_ids"]) == set(recording_ids)

    readme_text = (bundle_path / "README.md").read_text(encoding="utf-8")
    assert bundle_path.name in readme_text
    assert "cross_stream" in readme_text.lower()

    leftover = [p.name for p in output_root.iterdir() if p.name.startswith(".tmp_")]
    assert leftover == [], f"leftover tmp dirs: {leftover}"
