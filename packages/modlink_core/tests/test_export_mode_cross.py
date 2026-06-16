from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from modlink_core.replay.export_modes.cross import export_cross_recording_stream
from modlink_core.replay.export_request import ExportMode, ExportRequest, StreamSelection
from modlink_core.replay.reader import RecordedFrameRef
from modlink_sdk import FrameEnvelope, StreamDescriptor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STREAM_ID = "eeg_stream"
SAMPLE_RATE = 100.0  # Hz
CHUNK_SIZE = 4  # samples per frame
N_CHANNELS = 2


def _signal_descriptor() -> StreamDescriptor:
    return StreamDescriptor(
        device_id="dev.01",
        stream_key=STREAM_ID,
        payload_type="signal",
        nominal_sample_rate_hz=SAMPLE_RATE,
        chunk_size=CHUNK_SIZE,
        channel_names=("ch0", "ch1"),
        display_name=None,
        metadata={},
    )


def _frame_ref(frame_index: int, timestamp_ns: int) -> RecordedFrameRef:
    return RecordedFrameRef(
        stream_id=STREAM_ID,
        frame_index=frame_index,
        timestamp_ns=timestamp_ns,
        seq=frame_index,
        file_name=f"frame_{frame_index:04d}.npy",
        relative_timestamp_ns=timestamp_ns,
    )


def _frame_envelope(timestamp_ns: int, value_offset: float = 0.0) -> FrameEnvelope:
    # shape (N_CHANNELS, CHUNK_SIZE)
    data = np.arange(N_CHANNELS * CHUNK_SIZE, dtype=np.float32).reshape(N_CHANNELS, CHUNK_SIZE)
    data += value_offset
    return FrameEnvelope(
        device_id="dev.01",
        stream_key=STREAM_ID,
        timestamp_ns=timestamp_ns,
        data=data,
        seq=0,
    )


def _make_reader(recording_id: str, n_frames: int = 5, has_stream: bool = True) -> MagicMock:
    """Build a mock RecordingReader with n_frames for STREAM_ID."""
    reader = MagicMock()
    reader.recording_id = recording_id

    if has_stream:
        desc = _signal_descriptor()
        reader.descriptor.return_value = desc
        reader.descriptors.return_value = {STREAM_ID: desc}

        refs = tuple(_frame_ref(i, i * 10_000_000) for i in range(n_frames))
        reader.frames_for_stream.return_value = refs

        def _load(ref: RecordedFrameRef) -> FrameEnvelope:
            return _frame_envelope(ref.timestamp_ns)

        reader.load_frame.side_effect = _load
    else:
        reader.descriptor.return_value = None
        reader.descriptors.return_value = {}
        reader.frames_for_stream.return_value = ()

    return reader


def _make_store(readers: dict[str, MagicMock]) -> MagicMock:
    store = MagicMock()
    store.open.side_effect = lambda rec_id: readers[rec_id]
    return store


def _make_request(
    recording_ids: tuple[str, ...],
    concat_streams: bool = False,
    format_id: str = "signal_csv",
) -> ExportRequest:
    return ExportRequest(
        mode=ExportMode.CROSS_STREAM,
        recording_ids=recording_ids,
        streams=(StreamSelection(stream_id=STREAM_ID, format_id=format_id),),
        concat_streams=concat_streams,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_concat_csv_has_recording_id_column(tmp_path: Path) -> None:
    """concat=True → single CSV whose first column is recording_id."""
    rec_ids = ("rec_001", "rec_002")
    readers = {r: _make_reader(r) for r in rec_ids}
    store = _make_store(readers)
    request = _make_request(rec_ids, concat_streams=True)

    bundle = export_cross_recording_stream(request, store, tmp_path)

    concat_csv = bundle / "streams" / f"{STREAM_ID}_concat.csv"
    assert concat_csv.is_file(), "concat CSV not found"

    with concat_csv.open(encoding="utf-8", newline="") as fh:
        reader_csv = csv.reader(fh)
        header = next(reader_csv)

    assert header[0] == "recording_id", f"first column should be recording_id, got {header[0]!r}"
    assert header[1] == "timestamp_ns"


def test_concat_csv_row_count(tmp_path: Path) -> None:
    """2 recordings × 5 frames × 4 samples = 40 data rows."""
    rec_ids = ("rec_001", "rec_002")
    readers = {r: _make_reader(r, n_frames=5) for r in rec_ids}
    store = _make_store(readers)
    request = _make_request(rec_ids, concat_streams=True)

    bundle = export_cross_recording_stream(request, store, tmp_path)

    concat_csv = bundle / "streams" / f"{STREAM_ID}_concat.csv"
    with concat_csv.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))

    # rows[0] is header
    data_rows = rows[1:]
    expected = 2 * 5 * CHUNK_SIZE  # 40
    assert len(data_rows) == expected, f"expected {expected} data rows, got {len(data_rows)}"


def test_no_concat_per_recording_subdirs(tmp_path: Path) -> None:
    """concat=False → recordings/<id>/streams/<stream>.csv for each recording."""
    rec_ids = ("rec_001", "rec_002")
    readers = {r: _make_reader(r) for r in rec_ids}
    store = _make_store(readers)
    request = _make_request(rec_ids, concat_streams=False)

    bundle = export_cross_recording_stream(request, store, tmp_path)

    for rec_id in rec_ids:
        csv_path = bundle / "recordings" / rec_id / "streams" / f"{STREAM_ID}.csv"
        assert csv_path.is_file(), f"expected CSV at {csv_path.relative_to(bundle)}"

    # concat path should NOT exist
    assert not (bundle / "streams").exists()


def test_missing_stream_skipped(tmp_path: Path) -> None:
    """A recording without the target stream is skipped; others still export."""
    rec_ids = ("rec_001", "rec_002", "rec_003")
    readers = {
        "rec_001": _make_reader("rec_001", has_stream=True),
        "rec_002": _make_reader("rec_002", has_stream=False),  # missing
        "rec_003": _make_reader("rec_003", has_stream=True),
    }
    store = _make_store(readers)
    request = _make_request(rec_ids, concat_streams=False)

    bundle = export_cross_recording_stream(request, store, tmp_path)

    # rec_001 and rec_003 should have CSVs
    assert (bundle / "recordings" / "rec_001" / "streams" / f"{STREAM_ID}.csv").is_file()
    assert (bundle / "recordings" / "rec_003" / "streams" / f"{STREAM_ID}.csv").is_file()

    # rec_002 should NOT have a directory
    assert not (bundle / "recordings" / "rec_002").exists()


def test_manifest_has_skipped_recordings(tmp_path: Path) -> None:
    """Skipped recording appears in manifest skipped_recordings list."""
    rec_ids = ("rec_001", "rec_002")
    readers = {
        "rec_001": _make_reader("rec_001", has_stream=True),
        "rec_002": _make_reader("rec_002", has_stream=False),  # missing
    }
    store = _make_store(readers)
    request = _make_request(rec_ids, concat_streams=False)

    bundle = export_cross_recording_stream(request, store, tmp_path)

    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "cross_stream"
    assert manifest["stream_key"] == STREAM_ID
    assert "rec_002" in manifest["skipped_recordings"]
    assert "rec_001" not in manifest["skipped_recordings"]
    assert "rec_001" in manifest["recording_ids"]
