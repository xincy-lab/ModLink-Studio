from __future__ import annotations

import csv
from pathlib import Path

from modlink_core.models import ReplayMarker, ReplaySegment
from modlink_core.replay.format.annotations import write_markers_csv, write_segments_csv


def test_markers_empty_writes_header(tmp_path: Path) -> None:
    out = tmp_path / "markers.csv"
    write_markers_csv([], out)
    assert out.read_bytes() == b"timestamp_ns,label\r\n"


def test_markers_with_data(tmp_path: Path) -> None:
    markers = [
        ReplayMarker(timestamp_ns=1000, label="start"),
        ReplayMarker(timestamp_ns=2000, label="end"),
    ]
    out = tmp_path / "markers.csv"
    write_markers_csv(markers, out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert lines[0] == "timestamp_ns,label"
    assert lines[1] == "1000,start"
    assert lines[2] == "2000,end"


def test_segments_empty_writes_header(tmp_path: Path) -> None:
    out = tmp_path / "segments.csv"
    write_segments_csv([], out)
    assert out.read_bytes() == b"start_ns,end_ns,label\r\n"


def test_segments_with_data(tmp_path: Path) -> None:
    segments = [
        ReplaySegment(start_ns=0, end_ns=5000, label="phase1"),
        ReplaySegment(start_ns=5000, end_ns=10000, label="phase2"),
    ]
    out = tmp_path / "segments.csv"
    write_segments_csv(segments, out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert lines[0] == "start_ns,end_ns,label"
    assert lines[1] == "0,5000,phase1"
    assert lines[2] == "5000,10000,phase2"


def test_marker_timestamp_is_int(tmp_path: Path) -> None:
    markers = [ReplayMarker(timestamp_ns=123456789, label="check")]
    out = tmp_path / "markers.csv"
    write_markers_csv(markers, out)
    with out.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        row = next(reader)
    # Must parse as int without error, and must not contain a decimal point
    ts = row["timestamp_ns"]
    assert "." not in ts
    assert int(ts) == 123456789
