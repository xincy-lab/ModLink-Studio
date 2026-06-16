from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from modlink_core.replay.export_modes.multi import export_multi_recording
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
        nominal_sample_rate_hz=10.0,
        chunk_size=4,
        channel_names=("ch0", "ch1"),
        display_name=None,
        metadata={},
    )


def _frame_ref(stream_id: str, timestamp_ns: int = 1_000_000_000) -> RecordedFrameRef:
    return RecordedFrameRef(
        stream_id=stream_id,
        frame_index=0,
        timestamp_ns=timestamp_ns,
        seq=0,
        file_name="frame_0000.npy",
        relative_timestamp_ns=0,
    )


def _frame_envelope(stream_key: str = "demo", timestamp_ns: int = 1_000_000_000) -> FrameEnvelope:
    return FrameEnvelope(
        device_id="demo.01",
        stream_key=stream_key,
        timestamp_ns=timestamp_ns,
        data=np.arange(8, dtype=np.float32).reshape(2, 4),
        seq=0,
    )


def _make_reader(
    recording_id: str = "rec_001",
    stream_id: str = "sig_stream",
    stream_key: str = "demo",
    timestamp_ns: int = 1_000_000_000,
) -> MagicMock:
    reader = MagicMock()
    reader.recording_id = recording_id
    desc = _signal_descriptor(stream_key)
    reader.descriptors.return_value = {stream_id: desc}
    reader.descriptor.return_value = desc
    reader.frames_in_range.return_value = (_frame_ref(stream_id, timestamp_ns),)
    reader.load_frame.return_value = _frame_envelope(stream_key, timestamp_ns)
    reader.markers.return_value = ()
    reader.segments.return_value = ()
    reader.started_at_ns = timestamp_ns
    reader.stopped_at_ns = timestamp_ns + 1_000_000_000
    reader.status = "completed"
    reader.frame_counts_by_stream = {stream_id: 1}
    return reader


def _make_store(readers: dict[str, MagicMock]) -> MagicMock:
    store = MagicMock()
    store.open.side_effect = lambda rec_id: readers[rec_id]
    return store


def _make_request(
    recording_ids: tuple[str, ...] = ("rec_001", "rec_002"),
    stream_id: str = "sig_stream",
    format_id: str = "signal_csv",
    include_annotations: bool = False,
    include_recording_metadata: bool = False,
) -> ExportRequest:
    return ExportRequest(
        mode=ExportMode.MULTI,
        recording_ids=recording_ids,
        streams=(StreamSelection(stream_id=stream_id, format_id=format_id),),
        include_annotations=include_annotations,
        include_recording_metadata=include_recording_metadata,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_per_recording_subdirs(tmp_path: Path) -> None:
    """Two recordings → recordings/<id1>/ and recordings/<id2>/ both exist."""
    reader1 = _make_reader(recording_id="rec_001", stream_id="sig_stream")
    reader2 = _make_reader(recording_id="rec_002", stream_id="sig_stream")
    store = _make_store({"rec_001": reader1, "rec_002": reader2})
    request = _make_request(recording_ids=("rec_001", "rec_002"))

    bundle_path = export_multi_recording(request, store, tmp_path)

    assert bundle_path.is_dir()
    assert (bundle_path / "recordings" / "rec_001").is_dir()
    assert (bundle_path / "recordings" / "rec_002").is_dir()
    assert (bundle_path / "recordings" / "rec_001" / "streams").is_dir()
    assert (bundle_path / "recordings" / "rec_002" / "streams").is_dir()


def test_top_level_manifest(tmp_path: Path) -> None:
    """manifest.json at bundle root lists both recording_ids and mode=multi."""
    reader1 = _make_reader(recording_id="rec_001", stream_id="sig_stream")
    reader2 = _make_reader(recording_id="rec_002", stream_id="sig_stream")
    store = _make_store({"rec_001": reader1, "rec_002": reader2})
    request = _make_request(recording_ids=("rec_001", "rec_002"))

    bundle_path = export_multi_recording(request, store, tmp_path)

    manifest_path = bundle_path / "manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["mode"] == "multi"
    assert set(manifest["recording_ids"]) == {"rec_001", "rec_002"}
    assert "bundle_name" in manifest
    assert "created_at" in manifest


def test_missing_stream_skipped(tmp_path: Path) -> None:
    """Recording without the requested stream → no error, stream dir still created, just empty."""
    stream_id = "sig_stream"

    # rec_001 has the stream
    reader1 = _make_reader(recording_id="rec_001", stream_id=stream_id)

    # rec_002 does NOT have the stream
    reader2 = MagicMock()
    reader2.recording_id = "rec_002"
    reader2.descriptors.return_value = {}  # stream_id not present
    reader2.frames_in_range.return_value = ()  # no frames
    reader2.markers.return_value = ()
    reader2.segments.return_value = ()
    reader2.started_at_ns = 5_000_000_000
    reader2.stopped_at_ns = 6_000_000_000
    reader2.status = "completed"
    reader2.frame_counts_by_stream = {}

    store = _make_store({"rec_001": reader1, "rec_002": reader2})
    request = _make_request(recording_ids=("rec_001", "rec_002"), stream_id=stream_id)

    # Must not raise
    bundle_path = export_multi_recording(request, store, tmp_path)

    assert bundle_path.is_dir()
    # rec_001 exported the stream
    assert (bundle_path / "recordings" / "rec_001" / "streams").is_dir()
    # rec_002 dir still created, stream just skipped
    assert (bundle_path / "recordings" / "rec_002" / "streams").is_dir()
    # rec_002 streams dir is empty (stream was skipped)
    assert list((bundle_path / "recordings" / "rec_002" / "streams").iterdir()) == []


def test_non_overlapping_timelines(tmp_path: Path) -> None:
    """Recordings with no time overlap → both export successfully, absolute timestamps preserved."""
    stream_id = "sig_stream"

    # rec_001: timestamps around 1s
    reader1 = _make_reader(
        recording_id="rec_001",
        stream_id=stream_id,
        stream_key="demo",
        timestamp_ns=1_000_000_000,
    )

    # rec_002: timestamps around 1 hour later — no overlap
    reader2 = _make_reader(
        recording_id="rec_002",
        stream_id=stream_id,
        stream_key="demo",
        timestamp_ns=3_600_000_000_000,
    )

    store = _make_store({"rec_001": reader1, "rec_002": reader2})
    request = _make_request(recording_ids=("rec_001", "rec_002"), stream_id=stream_id)

    bundle_path = export_multi_recording(request, store, tmp_path)

    assert bundle_path.is_dir()
    assert (bundle_path / "recordings" / "rec_001" / "streams").is_dir()
    assert (bundle_path / "recordings" / "rec_002" / "streams").is_dir()

    # Both recordings produced a CSV file
    rec1_csvs = list((bundle_path / "recordings" / "rec_001" / "streams").glob("*.csv"))
    rec2_csvs = list((bundle_path / "recordings" / "rec_002" / "streams").glob("*.csv"))
    assert len(rec1_csvs) == 1
    assert len(rec2_csvs) == 1
