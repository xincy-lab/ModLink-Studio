from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from modlink_core.models import ReplayMarker, ReplaySegment
from modlink_core.replay.export_modes.single import export_single_recording
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


def _frame_ref(stream_id: str) -> RecordedFrameRef:
    return RecordedFrameRef(
        stream_id=stream_id,
        frame_index=0,
        timestamp_ns=1_000_000_000,
        seq=0,
        file_name="frame_0000.npy",
        relative_timestamp_ns=0,
    )


def _frame_envelope(stream_key: str = "demo") -> FrameEnvelope:
    return FrameEnvelope(
        device_id="demo.01",
        stream_key=stream_key,
        timestamp_ns=1_000_000_000,
        data=np.arange(8, dtype=np.float32).reshape(2, 4),
        seq=0,
    )


def _make_reader(
    recording_id: str = "rec_001",
    stream_id: str = "sig_stream",
    stream_key: str = "demo",
) -> MagicMock:
    reader = MagicMock()
    reader.recording_id = recording_id
    desc = _signal_descriptor(stream_key)
    reader.descriptors.return_value = {stream_id: desc}
    reader.descriptor.return_value = desc
    reader.frames_in_range.return_value = (_frame_ref(stream_id),)
    reader.load_frame.return_value = _frame_envelope(stream_key)
    reader.markers.return_value = (ReplayMarker(timestamp_ns=500_000_000, label="start"),)
    reader.segments.return_value = (ReplaySegment(start_ns=0, end_ns=1_000_000_000, label="seg1"),)
    reader.started_at_ns = 0
    reader.stopped_at_ns = 1_000_000_000
    reader.status = "completed"
    reader.frame_counts_by_stream = {stream_id: 1}
    return reader


def _make_request(
    recording_id: str = "rec_001",
    stream_id: str = "sig_stream",
    format_id: str = "signal_csv",
    include_annotations: bool = True,
    include_recording_metadata: bool = True,
) -> ExportRequest:
    return ExportRequest(
        mode=ExportMode.SINGLE,
        recording_ids=(recording_id,),
        streams=(StreamSelection(stream_id=stream_id, format_id=format_id),),
        include_annotations=include_annotations,
        include_recording_metadata=include_recording_metadata,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_bundle_structure(tmp_path: Path) -> None:
    reader = _make_reader()
    request = _make_request()

    bundle_path = export_single_recording(request, reader, tmp_path)

    assert bundle_path.is_dir()
    assert (bundle_path / "README.md").is_file()
    assert (bundle_path / "manifest.json").is_file()
    assert (bundle_path / "streams").is_dir()

    manifest = json.loads((bundle_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "single"
    assert manifest["recording_id"] == "rec_001"
    assert len(manifest["streams"]) == 1


def test_annotations_written(tmp_path: Path) -> None:
    reader = _make_reader()
    request = _make_request(include_annotations=True)

    bundle_path = export_single_recording(request, reader, tmp_path)

    assert (bundle_path / "annotations" / "markers.csv").is_file()
    assert (bundle_path / "annotations" / "segments.csv").is_file()


def test_annotations_skipped(tmp_path: Path) -> None:
    reader = _make_reader()
    request = _make_request(include_annotations=False)

    bundle_path = export_single_recording(request, reader, tmp_path)

    assert not (bundle_path / "annotations").exists()


def test_progress_called_per_stream(tmp_path: Path) -> None:
    stream_id_a = "stream_a"
    stream_id_b = "stream_b"
    desc_a = _signal_descriptor("demo_a")
    desc_b = _signal_descriptor("demo_b")

    def load_frame_side_effect(ref: RecordedFrameRef) -> FrameEnvelope:
        sk = "demo_a" if ref.stream_id == stream_id_a else "demo_b"
        return FrameEnvelope(
            device_id="demo.01",
            stream_key=sk,
            timestamp_ns=1_000_000_000,
            data=np.arange(4, dtype=np.float32).reshape(2, 2),
            seq=0,
        )

    reader = MagicMock()
    reader.recording_id = "rec_001"
    reader.descriptors.return_value = {stream_id_a: desc_a, stream_id_b: desc_b}
    reader.descriptor.side_effect = lambda sid: desc_a if sid == stream_id_a else desc_b
    reader.frames_in_range.side_effect = lambda sid, s, e: (_frame_ref(sid),)
    reader.load_frame.side_effect = load_frame_side_effect
    reader.markers.return_value = ()
    reader.segments.return_value = ()
    reader.started_at_ns = 0
    reader.stopped_at_ns = 1_000_000_000
    reader.status = "completed"
    reader.frame_counts_by_stream = {stream_id_a: 1, stream_id_b: 1}

    request = ExportRequest(
        mode=ExportMode.SINGLE,
        recording_ids=("rec_001",),
        streams=(
            StreamSelection(stream_id=stream_id_a, format_id="signal_csv"),
            StreamSelection(stream_id=stream_id_b, format_id="signal_csv"),
        ),
        include_annotations=False,
        include_recording_metadata=False,
    )

    called_with: list[str] = []
    export_single_recording(request, reader, tmp_path, progress_fn=called_with.append)

    assert called_with == [stream_id_a, stream_id_b]


def test_atomic_write(tmp_path: Path) -> None:
    reader = _make_reader()
    request = _make_request()

    with patch(
        "modlink_core.replay.export_modes.single.write_signal_csv",
        side_effect=RuntimeError("simulated crash"),
    ):
        with pytest.raises(RuntimeError, match="simulated crash"):
            export_single_recording(request, reader, tmp_path)

    # ExportPackageWriter cleans up the tmp dir on failure — nothing left
    assert list(tmp_path.iterdir()) == []
