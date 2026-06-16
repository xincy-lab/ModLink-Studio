from __future__ import annotations

import pytest

from modlink_core.replay.export_request import (
    ExportMode,
    ExportRequest,
    StreamSelection,
)

# --- helpers ---


def make_stream(stream_id: str = "s1", format_id: str = "signal_csv") -> StreamSelection:
    return StreamSelection(stream_id=stream_id, format_id=format_id)


# --- StreamSelection tests ---


def test_invalid_format_id() -> None:
    with pytest.raises(ValueError, match="format_id"):
        StreamSelection(stream_id="s1", format_id="unknown_format")


def test_empty_stream_id() -> None:
    with pytest.raises(ValueError, match="stream_id must not be empty"):
        StreamSelection(stream_id="", format_id="signal_csv")


# --- ExportRequest mode tests ---


def test_single_mode_valid() -> None:
    req = ExportRequest(
        mode=ExportMode.SINGLE,
        recording_ids=("rec1",),
        streams=(make_stream(),),
    )
    assert req.mode == ExportMode.SINGLE


def test_single_mode_too_many_recordings() -> None:
    with pytest.raises(ValueError, match="SINGLE mode requires exactly 1 recording_id"):
        ExportRequest(
            mode=ExportMode.SINGLE,
            recording_ids=("rec1", "rec2"),
            streams=(make_stream(),),
        )


def test_timeslice_requires_time_range() -> None:
    with pytest.raises(ValueError, match="TIMESLICE mode requires time_range_ns"):
        ExportRequest(
            mode=ExportMode.TIMESLICE,
            recording_ids=("rec1",),
            streams=(make_stream(),),
            time_range_ns=None,
        )


def test_timeslice_valid() -> None:
    req = ExportRequest(
        mode=ExportMode.TIMESLICE,
        recording_ids=("rec1",),
        streams=(make_stream(),),
        time_range_ns=(0, 1000),
    )
    assert req.time_range_ns == (0, 1000)


def test_multi_requires_two_recordings() -> None:
    with pytest.raises(ValueError, match="MULTI mode requires at least 2 recording_ids"):
        ExportRequest(
            mode=ExportMode.MULTI,
            recording_ids=("rec1",),
            streams=(make_stream(),),
        )


def test_multi_valid() -> None:
    req = ExportRequest(
        mode=ExportMode.MULTI,
        recording_ids=("rec1", "rec2"),
        streams=(make_stream(),),
    )
    assert len(req.recording_ids) == 2


def test_cross_stream_valid() -> None:
    req = ExportRequest(
        mode=ExportMode.CROSS_STREAM,
        recording_ids=("rec1", "rec2", "rec3"),
        streams=(make_stream(),),
        concat_streams=True,
    )
    assert req.mode == ExportMode.CROSS_STREAM
    assert req.concat_streams is True


def test_time_range_start_gte_end() -> None:
    with pytest.raises(ValueError, match="must be < end"):
        ExportRequest(
            mode=ExportMode.TIMESLICE,
            recording_ids=("rec1",),
            streams=(make_stream(),),
            time_range_ns=(1000, 500),
        )


def test_defaults() -> None:
    req = ExportRequest(
        mode=ExportMode.SINGLE,
        recording_ids=("rec1",),
        streams=(make_stream(),),
    )
    assert req.include_annotations is True
    assert req.include_recording_metadata is True
    assert req.include_raw is False
    assert req.package_as_zip is False
    assert req.concat_streams is False
