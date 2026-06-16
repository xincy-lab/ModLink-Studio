from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PACKAGE_ROOT.parents[1]
for path in (
    PACKAGE_ROOT,
    WORKSPACE_ROOT / "packages" / "modlink_sdk",
    WORKSPACE_ROOT / "packages" / "modlink_core",
):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from datetime import UTC

from modlink_core.models import ReplayRecordingSummary
from modlink_ui.features.replay.recordings_page import _format_tooltip


def test_format_tooltip_full_metadata() -> None:
    summary = ReplayRecordingSummary(
        recording_id="rec-001",
        recording_label="My Session",
        recording_path="/data/rec-001",
        stream_ids=("s1", "s2"),
        session_name="Session A",
        experiment_name="Exp B",
        started_at_ns=1_700_000_000_000_000_000,  # 2023-11-14 22:13:20 UTC
        duration_ns=3_661_000_000_000,  # 1h 1m 1s
        status="completed",
        total_frames=12345,
    )
    tooltip = _format_tooltip(summary)

    assert "01:01:01" in tooltip, "duration should be formatted as HH:MM:SS"
    assert "12,345" in tooltip, "frame count should be comma-formatted"
    assert "2 streams" in tooltip, "stream count should appear"
    from datetime import datetime

    expected_date = (
        datetime.fromtimestamp(1_700_000_000_000_000_000 / 1_000_000_000, tz=UTC)
        .astimezone()
        .strftime("%Y-%m-%d")
    )
    assert expected_date in tooltip, "recording date should appear"
    assert "Session A" in tooltip
    assert "Exp B" in tooltip
    assert "状态" not in tooltip, "no status line for non-failed recording"


def test_format_tooltip_graceful_degradation() -> None:
    summary = ReplayRecordingSummary(
        recording_id="rec-002",
        recording_label="Bare Recording",
        recording_path="/data/rec-002",
        stream_ids=("s1",),
        # all optional fields left as None / default
    )
    tooltip = _format_tooltip(summary)

    lines = tooltip.splitlines()
    assert lines[0] == "Bare Recording", "first line should be the title"
    assert "未知" not in tooltip, "no placeholder text for missing fields"
    assert "时长" not in tooltip, "no duration line when duration_ns is None"
    assert "帧数" not in tooltip, "no frame count line when total_frames is None"
    assert "录制时间" not in tooltip, "no timestamp line when started_at_ns is None"
    assert "状态" not in tooltip, "no status line when status is None"
    assert "Session" not in tooltip, "no session line when session_name is None"
    assert "Experiment" not in tooltip, "no experiment line when experiment_name is None"
