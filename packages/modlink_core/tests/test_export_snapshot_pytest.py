from __future__ import annotations

from modlink_core.models import ExportJobSnapshot


def _make_snapshot(**kwargs: object) -> ExportJobSnapshot:
    defaults: dict[str, object] = {
        "job_id": "abc123",
        "recording_id": "rec1",
        "state": "queued",
        "progress": 0.0,
        "output_path": None,
        "error": None,
    }
    defaults.update(kwargs)
    return ExportJobSnapshot(**defaults)  # type: ignore[arg-type]


def test_snapshot_has_no_format_id() -> None:
    snap = _make_snapshot()
    assert not hasattr(snap, "format_id")


def test_snapshot_has_request_summary() -> None:
    snap = _make_snapshot(request_summary="single: 3 streams")
    assert snap.request_summary == "single: 3 streams"


def test_snapshot_request_summary_defaults_to_empty_string() -> None:
    snap = _make_snapshot()
    assert snap.request_summary == ""
