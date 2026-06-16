from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from modlink_core.bus import StreamBus
from modlink_core.event_stream import BackendEventBroker
from modlink_core.models import (
    ExportJobSnapshot,
    ReplayMarker,
    ReplayRecordingSummary,
    ReplaySegment,
)
from modlink_core.replay import ReplayBackend
from modlink_core.replay.export_request import ExportMode, ExportRequest, StreamSelection
from modlink_core.replay.reader import RecordingReader
from modlink_core.settings import SettingsStore, declare_core_settings
from modlink_core.storage import (
    add_recording_marker,
    add_recording_segment,
    append_recording_frame,
    create_recording,
    finalize_recording,
    list_recordings,
    load_recording_frame_data,
    read_recording,
    read_recording_frames,
    read_recording_markers,
    read_recording_segments,
    read_recording_stream,
)


def test_recording_storage_read_api_lists_and_reads_valid_recordings(
    tmp_path,
    descriptor_factory,
    frame_factory,
) -> None:
    descriptor = descriptor_factory(payload_type="signal", chunk_size=3, channel_names=("f3", "f4"))
    frame = frame_factory(descriptor, timestamp_ns=1_700_000_000_123_456_789, seq=11)
    recording_id = create_recording(
        tmp_path,
        {descriptor.stream_id: descriptor},
        recording_label="baseline",
    )
    append_recording_frame(tmp_path, recording_id, frame, frame_index=1)
    add_recording_marker(tmp_path, recording_id, 1_700_000_000_123_456_999, "start")
    add_recording_segment(
        tmp_path,
        recording_id,
        1_700_000_000_123_456_999,
        1_700_000_000_223_456_999,
        "segment_a",
    )
    (tmp_path / "recordings" / "broken").mkdir(parents=True)

    manifests = list_recordings(tmp_path)

    assert manifests == [
        {
            "recording_id": recording_id,
            "recording_label": "baseline",
            "session_name": None,
            "experiment_name": None,
            "stream_ids": [descriptor.stream_id],
        }
    ]
    assert read_recording(tmp_path, recording_id) == manifests[0]
    assert (
        read_recording_stream(tmp_path, recording_id, descriptor.stream_id)["stream_id"]
        == descriptor.stream_id
    )
    assert read_recording_markers(tmp_path, recording_id) == [
        {"timestamp_ns": "1700000000123456999", "label": "start"}
    ]
    assert read_recording_segments(tmp_path, recording_id) == [
        {
            "start_ns": "1700000000123456999",
            "end_ns": "1700000000223456999",
            "label": "segment_a",
        }
    ]
    assert read_recording_frames(tmp_path, recording_id, descriptor.stream_id) == [
        {
            "frame_index": "1",
            "timestamp_ns": "1700000000123456789",
            "seq": "11",
            "file_name": "000001.npz",
        }
    ]
    np.testing.assert_array_equal(
        load_recording_frame_data(tmp_path, recording_id, descriptor.stream_id, "000001.npz"),
        np.ascontiguousarray(frame.data),
    )


def test_recording_reader_merges_frames_and_normalizes_annotations(
    tmp_path,
    descriptor_factory,
    frame_factory,
) -> None:
    signal_descriptor = descriptor_factory(
        payload_type="signal",
        stream_key="signal",
        chunk_size=2,
        channel_names=("c3", "c4"),
    )
    raster_descriptor = descriptor_factory(
        payload_type="raster",
        stream_key="raster",
        chunk_size=1,
    )
    recording_id = create_recording(
        tmp_path,
        {
            signal_descriptor.stream_id: signal_descriptor,
            raster_descriptor.stream_id: raster_descriptor,
        },
        recording_label="reader_case",
    )
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(signal_descriptor, timestamp_ns=1_000_000_000, seq=1),
        frame_index=1,
    )
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(raster_descriptor, timestamp_ns=1_050_000_000, seq=2, line_length=4),
        frame_index=1,
    )
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(signal_descriptor, timestamp_ns=1_100_000_000, seq=3),
        frame_index=2,
    )
    add_recording_marker(tmp_path, recording_id, 1_025_000_000, "marker_a")
    add_recording_segment(tmp_path, recording_id, 1_020_000_000, 1_080_000_000, "segment_a")

    reader = RecordingReader(tmp_path / "recordings" / recording_id)

    assert reader.recording_id == recording_id
    assert reader.recording_label == "reader_case"
    assert reader.duration_ns == 100_000_000
    assert reader.stream_ids() == (signal_descriptor.stream_id, raster_descriptor.stream_id)
    assert [ref.stream_id for ref in reader.frames()] == [
        signal_descriptor.stream_id,
        raster_descriptor.stream_id,
        signal_descriptor.stream_id,
    ]
    assert [ref.relative_timestamp_ns for ref in reader.frames()] == [0, 50_000_000, 100_000_000]
    assert reader.markers() == (ReplayMarker(timestamp_ns=25_000_000, label="marker_a"),)
    assert reader.segments() == (
        ReplaySegment(start_ns=20_000_000, end_ns=80_000_000, label="segment_a"),
    )
    envelope = reader.load_frame(reader.frames()[0])
    assert envelope.stream_id == signal_descriptor.stream_id
    assert envelope.seq == 1


def test_replay_backend_replays_on_its_own_bus(
    tmp_path,
    descriptor_factory,
    frame_factory,
) -> None:
    descriptor = descriptor_factory(payload_type="signal", stream_key="signal", chunk_size=2)
    recording_id = create_recording(tmp_path, {descriptor.stream_id: descriptor})
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(descriptor, timestamp_ns=1_000_000_000, seq=1),
        frame_index=1,
    )
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(descriptor, timestamp_ns=1_050_000_000, seq=2),
        frame_index=2,
    )
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(descriptor, timestamp_ns=1_100_000_000, seq=3),
        frame_index=3,
    )

    settings = _build_settings(tmp_path)
    backend = ReplayBackend(settings=settings)
    backend.start()

    try:
        backend.refresh_recordings().result(1.0)
        backend.open_recording(tmp_path / "recordings" / recording_id).result(1.0)
        replay_stream = backend.bus.open_frame_stream(maxsize=8, consumer_name="replay-test")
        live_bus = StreamBus(event_broker=BackendEventBroker())
        live_bus.add_descriptor(descriptor)
        live_stream = live_bus.open_frame_stream(maxsize=8, consumer_name="live-test")

        backend.play().result(1.0)
        received = _read_frames(replay_stream, expected_count=3, timeout=1.5)
        _wait_until(lambda: backend.snapshot().state == "finished", timeout=1.5)

        assert [frame.seq for frame in received] == [1, 2, 3]
        with pytest.raises(queue.Empty):
            live_stream.read(timeout=0.05)

        backend.stop().result(1.0)
        assert backend.snapshot().state == "ready"
        assert backend.snapshot().position_ns == 0
    finally:
        backend.shutdown()


def test_replay_backend_play_after_seek_starts_from_seeked_position(
    tmp_path,
    descriptor_factory,
    frame_factory,
) -> None:
    """After seeking to a position, play should emit only frames after that position."""
    descriptor = descriptor_factory(payload_type="signal", stream_key="signal", chunk_size=2)
    recording_id = create_recording(tmp_path, {descriptor.stream_id: descriptor})
    # Frame 1 at t=0ms (relative)
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(descriptor, timestamp_ns=1_000_000_000, seq=1),
        frame_index=1,
    )
    # Frame 2 at t=50ms (relative)
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(descriptor, timestamp_ns=1_050_000_000, seq=2),
        frame_index=2,
    )
    # Frame 3 at t=100ms (relative)
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(descriptor, timestamp_ns=1_100_000_000, seq=3),
        frame_index=3,
    )

    settings = _build_settings(tmp_path)
    backend = ReplayBackend(settings=settings)
    backend.start()

    try:
        backend.refresh_recordings().result(1.0)
        backend.open_recording(tmp_path / "recordings" / recording_id).result(1.0)
        replay_stream = backend.bus.open_frame_stream(maxsize=8, consumer_name="replay-test")

        # Seek to 60ms — past frame 1 (0ms) and frame 2 (50ms), before frame 3 (100ms)
        backend.seek(60_000_000).result(1.0)
        snapshot = backend.snapshot()
        assert snapshot.position_ns == 60_000_000
        assert snapshot.state == "ready"

        # Now play — should only emit frame 3 (at 100ms), not frames 1 and 2
        backend.play().result(1.0)
        _wait_until(lambda: backend.snapshot().state == "finished", timeout=2.0)

        received = _read_frames(replay_stream, expected_count=1, timeout=1.0)
        assert [frame.seq for frame in received] == [3]
    finally:
        backend.shutdown()


def test_replay_backend_play_after_seek_from_finished_starts_from_seeked_position(
    tmp_path,
    descriptor_factory,
    frame_factory,
) -> None:
    """After finishing playback, seeking, then playing again should start from seeked position."""
    descriptor = descriptor_factory(payload_type="signal", stream_key="signal", chunk_size=2)
    recording_id = create_recording(tmp_path, {descriptor.stream_id: descriptor})
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(descriptor, timestamp_ns=1_000_000_000, seq=1),
        frame_index=1,
    )
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(descriptor, timestamp_ns=1_050_000_000, seq=2),
        frame_index=2,
    )
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(descriptor, timestamp_ns=1_100_000_000, seq=3),
        frame_index=3,
    )

    settings = _build_settings(tmp_path)
    backend = ReplayBackend(settings=settings)
    backend.start()

    try:
        backend.refresh_recordings().result(1.0)
        backend.open_recording(tmp_path / "recordings" / recording_id).result(1.0)
        replay_stream = backend.bus.open_frame_stream(maxsize=16, consumer_name="replay-test")

        # Play to completion
        backend.play().result(1.0)
        _wait_until(lambda: backend.snapshot().state == "finished", timeout=2.0)
        # Drain all frames from first playback
        _read_frames(replay_stream, expected_count=3, timeout=1.0)

        # Seek to 60ms (past frame 1 and 2, before frame 3)
        backend.seek(60_000_000).result(1.0)
        snapshot = backend.snapshot()
        assert snapshot.state == "paused"
        assert snapshot.position_ns == 60_000_000

        # Play again — should only emit frame 3
        backend.play().result(1.0)
        _wait_until(lambda: backend.snapshot().state == "finished", timeout=2.0)
        received = _read_frames(replay_stream, expected_count=1, timeout=1.0)
        assert [frame.seq for frame in received] == [3]
    finally:
        backend.shutdown()


def test_replay_export_job_fails_when_format_has_no_matching_streams(
    tmp_path,
    descriptor_factory,
    frame_factory,
) -> None:
    descriptor = descriptor_factory(payload_type="signal", stream_key="signal", chunk_size=2)
    recording_id = create_recording(tmp_path, {descriptor.stream_id: descriptor})
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(descriptor, timestamp_ns=1_000_000_000, seq=1),
        frame_index=1,
    )

    settings = _build_settings(tmp_path)
    backend = ReplayBackend(settings=settings)
    backend.start()

    try:
        backend.open_recording(tmp_path / "recordings" / recording_id).result(1.0)
        job = backend.start_export("field_npz").result(1.0)
        failed = _wait_for_job(backend, job.job_id, timeout=2.0)
        assert failed.state == "failed"
        assert failed.error is not None
    finally:
        backend.shutdown()


def test_replay_backend_export_request_writes_single_bundle(
    tmp_path,
    descriptor_factory,
    frame_factory,
) -> None:
    descriptor = descriptor_factory(
        payload_type="signal",
        stream_key="signal",
        chunk_size=2,
        channel_names=("ch0", "ch1"),
    )
    recording_id = create_recording(tmp_path, {descriptor.stream_id: descriptor})
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(descriptor, timestamp_ns=1_000_000_000, seq=1),
        frame_index=1,
    )
    finalize_recording(
        tmp_path,
        recording_id,
        started_at_ns=1_000_000_000,
        stopped_at_ns=1_100_000_000,
        status="completed",
        frame_counts_by_stream={descriptor.stream_id: 1},
    )

    settings = _build_settings(tmp_path)
    backend = ReplayBackend(settings=settings)
    backend.start()

    try:
        request = ExportRequest(
            mode=ExportMode.SINGLE,
            recording_ids=(recording_id,),
            streams=(StreamSelection(stream_id=descriptor.stream_id, format_id="signal_csv"),),
        )
        job = backend.start_export(request).result(1.0)
        completed = _wait_for_job(backend, job.job_id, timeout=2.0)
    finally:
        backend.shutdown()

    assert completed.state == "completed"
    assert completed.output_path is not None
    output_path = Path(completed.output_path)
    assert (output_path / "manifest.json").is_file()
    assert (output_path / "README.md").is_file()
    assert (output_path / "streams" / "signal.csv").is_file()


def test_replay_backend_export_request_writes_multi_bundle_without_open_reader(
    tmp_path,
    descriptor_factory,
    frame_factory,
) -> None:
    descriptor = descriptor_factory(
        payload_type="signal",
        stream_key="signal",
        chunk_size=2,
        channel_names=("ch0", "ch1"),
    )
    recording_ids: list[str] = []
    for index in range(2):
        recording_id = create_recording(tmp_path, {descriptor.stream_id: descriptor})
        append_recording_frame(
            tmp_path,
            recording_id,
            frame_factory(descriptor, timestamp_ns=1_000_000_000 + index, seq=index),
            frame_index=1,
        )
        finalize_recording(
            tmp_path,
            recording_id,
            started_at_ns=1_000_000_000 + index,
            stopped_at_ns=1_100_000_000 + index,
            status="completed",
            frame_counts_by_stream={descriptor.stream_id: 1},
        )
        recording_ids.append(recording_id)

    output_root = tmp_path / "chosen_exports"
    settings = _build_settings(tmp_path)
    backend = ReplayBackend(settings=settings)
    backend.start()

    try:
        request = ExportRequest(
            mode=ExportMode.MULTI,
            recording_ids=tuple(recording_ids),
            streams=(StreamSelection(stream_id=descriptor.stream_id, format_id="signal_csv"),),
        )
        job = backend.start_export(request, output_root).result(1.0)
        completed = _wait_for_job(backend, job.job_id, timeout=2.0)
    finally:
        backend.shutdown()

    assert completed.state == "completed"
    assert completed.output_path is not None
    output_path = Path(completed.output_path)
    assert output_path.is_relative_to(output_root)
    for recording_id in recording_ids:
        assert (output_path / "recordings" / recording_id / "streams" / "signal.csv").is_file()


def test_replay_export_shutdown_cancels_running_job_and_cleans_tmp(
    tmp_path,
    descriptor_factory,
    frame_factory,
    monkeypatch,
) -> None:
    descriptor = descriptor_factory(
        payload_type="signal",
        stream_key="signal",
        chunk_size=2,
        channel_names=("ch0", "ch1"),
    )
    recording_id = create_recording(tmp_path, {descriptor.stream_id: descriptor})
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(descriptor, timestamp_ns=1_000_000_000, seq=1),
        frame_index=1,
    )
    finalize_recording(
        tmp_path,
        recording_id,
        started_at_ns=1_000_000_000,
        stopped_at_ns=1_100_000_000,
        status="completed",
        frame_counts_by_stream={descriptor.stream_id: 1},
    )

    export_started = threading.Event()
    allow_progress = threading.Event()
    output_root = tmp_path / "exports"

    def blocking_export(request, reader, output_root_dir, progress_fn):
        from modlink_core.replay.package_writer import ExportPackageWriter

        with ExportPackageWriter(Path(output_root_dir) / "blocking_bundle") as pkg:
            (pkg.root / "partial.txt").write_text("partial", encoding="utf-8")
            export_started.set()
            allow_progress.wait(1.0)
            progress_fn(request.streams[0].stream_id)
        raise AssertionError("cancelled export should not complete")

    monkeypatch.setattr(
        "modlink_core.replay.export.export_single_recording",
        blocking_export,
    )

    settings = _build_settings(tmp_path)
    backend = ReplayBackend(settings=settings)
    backend.start()

    request = ExportRequest(
        mode=ExportMode.SINGLE,
        recording_ids=(recording_id,),
        streams=(StreamSelection(stream_id=descriptor.stream_id, format_id="signal_csv"),),
    )
    job = backend.start_export(request, output_root).result(1.0)
    assert export_started.wait(1.0)

    backend.shutdown(timeout_ms=50)
    allow_progress.set()
    cancelled = _wait_for_job(backend, job.job_id, timeout=2.0)
    backend.shutdown(timeout_ms=1000)

    assert cancelled.state == "cancelled"
    assert cancelled.output_path is None
    assert cancelled.error is None
    assert not (output_root / "blocking_bundle").exists()
    assert list(output_root.glob(".tmp_*")) == []


def test_replay_export_shutdown_cancels_queued_jobs(
    tmp_path,
    descriptor_factory,
    frame_factory,
    monkeypatch,
) -> None:
    descriptor = descriptor_factory(
        payload_type="signal",
        stream_key="signal",
        chunk_size=2,
        channel_names=("ch0", "ch1"),
    )
    recording_id = create_recording(tmp_path, {descriptor.stream_id: descriptor})
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(descriptor, timestamp_ns=1_000_000_000, seq=1),
        frame_index=1,
    )
    finalize_recording(
        tmp_path,
        recording_id,
        started_at_ns=1_000_000_000,
        stopped_at_ns=1_100_000_000,
        status="completed",
        frame_counts_by_stream={descriptor.stream_id: 1},
    )

    export_started = threading.Event()
    release_export = threading.Event()
    calls = 0

    def blocking_export(request, reader, output_root_dir, progress_fn):
        nonlocal calls
        calls += 1
        export_started.set()
        release_export.wait(1.0)
        progress_fn(request.streams[0].stream_id)
        return Path(output_root_dir) / "unused"

    monkeypatch.setattr(
        "modlink_core.replay.export.export_single_recording",
        blocking_export,
    )

    settings = _build_settings(tmp_path)
    backend = ReplayBackend(settings=settings)
    backend.start()

    request = ExportRequest(
        mode=ExportMode.SINGLE,
        recording_ids=(recording_id,),
        streams=(StreamSelection(stream_id=descriptor.stream_id, format_id="signal_csv"),),
    )
    running_job = backend.start_export(request).result(1.0)
    queued_job = backend.start_export(request).result(1.0)
    assert export_started.wait(1.0)

    backend.shutdown(timeout_ms=50)
    release_export.set()
    running = _wait_for_job(backend, running_job.job_id, timeout=2.0)
    queued = _wait_for_job(backend, queued_job.job_id, timeout=2.0)
    backend.shutdown(timeout_ms=1000)

    assert running.state == "cancelled"
    assert queued.state == "cancelled"
    assert calls == 1


def _build_settings(tmp_path: Path) -> SettingsStore:
    settings = SettingsStore()
    declare_core_settings(settings)
    settings.storage.root_dir = str(tmp_path)
    settings.storage.export_root_dir = str(tmp_path / "exports")
    return settings


def _read_frames(frame_stream, *, expected_count: int, timeout: float) -> list:
    deadline = time.time() + timeout
    frames: list = []
    while time.time() < deadline and len(frames) < expected_count:
        try:
            frames.append(frame_stream.read(timeout=0.1))
        except queue.Empty:
            continue
    if len(frames) != expected_count:
        raise AssertionError(f"expected {expected_count} frames, got {len(frames)}")
    return frames


def _wait_until(predicate, *, timeout: float) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    if predicate():
        return
    raise AssertionError("condition not reached before timeout")


def _wait_for_job(backend: ReplayBackend, job_id: str, *, timeout: float) -> ExportJobSnapshot:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for job in backend.export_jobs():
            if job.job_id == job_id and job.state in {"completed", "failed", "cancelled"}:
                return job
        time.sleep(0.01)
    raise AssertionError("export job did not finish before timeout")


def test_replay_backend_delete_recording_removes_files_and_clears_open_reader(
    tmp_path,
    descriptor_factory,
    frame_factory,
) -> None:
    descriptor = descriptor_factory(payload_type="signal", stream_key="signal", chunk_size=2)
    recording_id = create_recording(tmp_path, {descriptor.stream_id: descriptor})
    append_recording_frame(
        tmp_path,
        recording_id,
        frame_factory(descriptor, timestamp_ns=1_000_000_000, seq=1),
        frame_index=1,
    )

    settings = _build_settings(tmp_path)
    backend = ReplayBackend(settings=settings)
    backend.start()

    try:
        backend.refresh_recordings().result(1.0)
        backend.open_recording(tmp_path / "recordings" / recording_id).result(1.0)
        assert backend.snapshot().recording_id == recording_id

        remaining = backend.delete_recording(recording_id).result(1.0)

        assert remaining == ()
        assert not (tmp_path / "recordings" / recording_id).exists()
        assert backend.snapshot().recording_id is None
        assert backend.snapshot().state == "idle"
        assert backend.bus.descriptors() == {}
    finally:
        backend.shutdown()


def test_replay_backend_delete_recording_keeps_other_open_recording(
    tmp_path,
    descriptor_factory,
    frame_factory,
) -> None:
    descriptor = descriptor_factory(payload_type="signal", stream_key="signal", chunk_size=2)
    keep_id = create_recording(
        tmp_path,
        {descriptor.stream_id: descriptor},
        recording_label="keep",
    )
    append_recording_frame(
        tmp_path,
        keep_id,
        frame_factory(descriptor, timestamp_ns=1_000_000_000, seq=1),
        frame_index=1,
    )
    drop_id = create_recording(
        tmp_path,
        {descriptor.stream_id: descriptor},
        recording_label="drop",
    )
    append_recording_frame(
        tmp_path,
        drop_id,
        frame_factory(descriptor, timestamp_ns=2_000_000_000, seq=1),
        frame_index=1,
    )

    settings = _build_settings(tmp_path)
    backend = ReplayBackend(settings=settings)
    backend.start()

    try:
        backend.refresh_recordings().result(1.0)
        backend.open_recording(tmp_path / "recordings" / keep_id).result(1.0)

        remaining = backend.delete_recording(drop_id).result(1.0)

        assert {summary.recording_id for summary in remaining} == {keep_id}
        assert backend.snapshot().recording_id == keep_id
        assert backend.bus.descriptor(descriptor.stream_id) is not None
    finally:
        backend.shutdown()


def test_replay_backend_delete_recording_raises_for_unknown_id(tmp_path) -> None:
    import pytest

    settings = _build_settings(tmp_path)
    backend = ReplayBackend(settings=settings)
    backend.start()

    try:
        with pytest.raises(RuntimeError, match="REPLAY_DELETE_NOT_FOUND"):
            backend.delete_recording("rec_nonexistent").result(1.0)
    finally:
        backend.shutdown()


def test_refresh_recordings_summary_includes_finalized_metadata(
    tmp_path,
    descriptor_factory,
) -> None:
    descriptor = descriptor_factory(payload_type="signal", stream_key="s1", chunk_size=2)
    recording_id = create_recording(
        tmp_path,
        {descriptor.stream_id: descriptor},
        recording_label="finalized_test",
    )
    finalize_recording(
        tmp_path,
        recording_id,
        started_at_ns=1_000_000_000,
        stopped_at_ns=61_000_000_000,
        status="completed",
        frame_counts_by_stream={descriptor.stream_id: 100},
    )

    settings = _build_settings(tmp_path)
    backend = ReplayBackend(settings=settings)
    backend.start()
    try:
        recordings = backend.refresh_recordings().result(5.0)
    finally:
        backend.shutdown()

    assert len(recordings) == 1
    summary: ReplayRecordingSummary = recordings[0]
    assert summary.started_at_ns == 1_000_000_000
    assert summary.duration_ns == 60_000_000_000
    assert summary.status == "completed"
    assert summary.total_frames == 100


def test_refresh_recordings_summary_old_recording_graceful_degradation(
    tmp_path,
    descriptor_factory,
) -> None:
    descriptor = descriptor_factory(payload_type="signal", stream_key="s1", chunk_size=2)
    create_recording(
        tmp_path,
        {descriptor.stream_id: descriptor},
        recording_label="old_recording",
    )
    # No finalize_recording call — simulates a recording without finalized metadata

    settings = _build_settings(tmp_path)
    backend = ReplayBackend(settings=settings)
    backend.start()
    try:
        recordings = backend.refresh_recordings().result(5.0)
    finally:
        backend.shutdown()

    assert len(recordings) == 1
    summary: ReplayRecordingSummary = recordings[0]
    assert summary.started_at_ns is None
    assert summary.duration_ns is None
    assert summary.status is None
    assert summary.total_frames is None
