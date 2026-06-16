from __future__ import annotations

import json
from pathlib import Path

from modlink_core.replay.reader import RecordingReader
from modlink_core.replay.store import RecordingStore


def _make_recording(root: Path, rec_id: str, stream_keys: list[str]) -> None:
    """Create a minimal on-disk recording structure that RecordingReader can open."""
    rec_dir = root / "recordings" / rec_id
    streams_dir = rec_dir / "streams"
    annotations_dir = rec_dir / "annotations"
    annotations_dir.mkdir(parents=True, exist_ok=True)

    stream_ids: list[str] = []
    for stream_key in stream_keys:
        stream_id = f"{stream_key}.01"
        stream_ids.append(stream_id)
        stream_dir = streams_dir / stream_id
        (stream_dir / "frames").mkdir(parents=True, exist_ok=True)
        (stream_dir / "stream.json").write_text(
            json.dumps(
                {
                    "stream_id": stream_id,
                    "descriptor": {
                        "device_id": "demo.01",
                        "stream_id": stream_id,
                        "stream_key": stream_key,
                        "payload_type": "signal",
                        "nominal_sample_rate_hz": 256.0,
                        "chunk_size": 32,
                        "channel_names": ["ch0", "ch1"],
                        "display_name": stream_key,
                        "metadata": {},
                    },
                }
            ),
            encoding="utf-8",
        )
        # frames.csv with header only (no data rows)
        (stream_dir / "frames.csv").write_text(
            "frame_index,timestamp_ns,seq,file_name\n",
            encoding="utf-8",
        )

    (rec_dir / "recording.json").write_text(
        json.dumps(
            {
                "recording_id": rec_id,
                "recording_label": None,
                "session_name": None,
                "experiment_name": None,
                "stream_ids": stream_ids,
            }
        ),
        encoding="utf-8",
    )


def test_list_recording_ids_empty(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path)
    assert store.list_recording_ids() == ()


def test_list_recording_ids_three(tmp_path: Path) -> None:
    for rec_id in ("rec_a", "rec_b", "rec_c"):
        _make_recording(tmp_path, rec_id, ["eeg"])

    store = RecordingStore(tmp_path)
    ids = store.list_recording_ids()
    assert len(ids) == 3
    assert set(ids) == {"rec_a", "rec_b", "rec_c"}


def test_open_returns_reader(tmp_path: Path) -> None:
    _make_recording(tmp_path, "rec_x", ["eeg"])
    store = RecordingStore(tmp_path)
    reader = store.open("rec_x")
    assert isinstance(reader, RecordingReader)


def test_find_recordings_with_stream(tmp_path: Path) -> None:
    _make_recording(tmp_path, "rec_1", ["eeg", "emg"])
    _make_recording(tmp_path, "rec_2", ["eeg"])
    _make_recording(tmp_path, "rec_3", ["emg"])

    store = RecordingStore(tmp_path)
    eeg_ids = store.find_recordings_with_stream("eeg")
    assert len(eeg_ids) == 2
    assert set(eeg_ids) == {"rec_1", "rec_2"}
