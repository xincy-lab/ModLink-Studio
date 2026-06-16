from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from modlink_core.replay.format.recording_metadata import write_recording_metadata_json
from modlink_sdk import StreamDescriptor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_descriptor(
    *,
    device_id: str = "test.01",
    stream_key: str = "eeg",
    payload_type: str = "signal",
    nominal_sample_rate_hz: float = 250.0,
    chunk_size: int = 10,
    channel_names: tuple[str, ...] = ("ch1", "ch2"),
) -> StreamDescriptor:
    return StreamDescriptor(
        device_id=device_id,
        stream_key=stream_key,
        payload_type=payload_type,
        nominal_sample_rate_hz=nominal_sample_rate_hz,
        chunk_size=chunk_size,
        channel_names=channel_names,
        display_name="Test EEG",
        metadata={},
    )


def _make_reader(
    *,
    recording_id: str = "rec_001",
    started_at_ns: int | None = 1_000_000_000,
    stopped_at_ns: int | None = 2_000_000_000,
    status: str | None = "completed",
    frame_counts: dict[str, int] | None = None,
    descriptors: dict[str, StreamDescriptor] | None = None,
) -> MagicMock:
    reader = MagicMock()
    reader.recording_id = recording_id
    reader.started_at_ns = started_at_ns
    reader.stopped_at_ns = stopped_at_ns
    reader.status = status
    reader.frame_counts_by_stream = frame_counts if frame_counts is not None else {"eeg": 5}
    reader.descriptors.return_value = (
        descriptors
        if descriptors is not None
        else {
            "eeg": _make_descriptor(),
        }
    )
    return reader


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_json_valid(tmp_path: Path) -> None:
    reader = _make_reader()
    out = tmp_path / "metadata.json"
    write_recording_metadata_json(reader, out)
    content = out.read_text(encoding="utf-8")
    parsed = json.loads(content)  # raises if invalid JSON
    assert isinstance(parsed, dict)


def test_has_required_keys(tmp_path: Path) -> None:
    reader = _make_reader()
    out = tmp_path / "metadata.json"
    write_recording_metadata_json(reader, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "recording_id" in data
    assert "started_at_ns" in data
    assert "streams" in data


def test_streams_have_descriptor_fields(tmp_path: Path) -> None:
    reader = _make_reader(
        descriptors={
            "eeg": _make_descriptor(device_id="dev.01", stream_key="eeg", payload_type="signal"),
            "emg": _make_descriptor(device_id="dev.02", stream_key="emg", payload_type="signal"),
        }
    )
    out = tmp_path / "metadata.json"
    write_recording_metadata_json(reader, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    for stream_id in ("eeg", "emg"):
        entry = data["streams"][stream_id]
        assert "device_id" in entry
        assert "stream_key" in entry
        assert "payload_type" in entry


def test_duration_computed(tmp_path: Path) -> None:
    reader = _make_reader(started_at_ns=1_000_000_000, stopped_at_ns=3_500_000_000)
    out = tmp_path / "metadata.json"
    write_recording_metadata_json(reader, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["duration_ns"] == 2_500_000_000


def test_duration_null_when_missing(tmp_path: Path) -> None:
    for started, stopped in [
        (None, 2_000_000_000),
        (1_000_000_000, None),
        (None, None),
    ]:
        reader = _make_reader(started_at_ns=started, stopped_at_ns=stopped)
        out = tmp_path / "metadata.json"
        write_recording_metadata_json(reader, out)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["duration_ns"] is None, (
            f"expected null for started={started}, stopped={stopped}"
        )
