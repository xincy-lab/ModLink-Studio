from __future__ import annotations

import os
from pathlib import Path

from modlink_core.replay.format.readme import generate_readme


def _default(**kwargs) -> str:
    defaults = dict(
        bundle_name="my_bundle",
        recording_ids=("rec-001", "rec-002"),
        mode="multi",
        time_range_ns=None,
        stream_keys=("eeg", "accel"),
        has_annotations=False,
        has_recording_metadata=False,
    )
    defaults.update(kwargs)
    return generate_readme(**defaults)  # type: ignore[arg-type]


def test_returns_string() -> None:
    result = _default()
    assert isinstance(result, str)


def test_contains_bundle_name() -> None:
    result = _default(bundle_name="export_2026")
    assert "export_2026" in result


def test_contains_recording_ids() -> None:
    result = _default(recording_ids=("rec-aaa", "rec-bbb"))
    assert "rec-aaa" in result
    assert "rec-bbb" in result


def test_time_range_included_when_present() -> None:
    result = _default(time_range_ns=(1_000_000, 5_000_000))
    assert "1000000" in result
    assert "5000000" in result


def test_time_range_omitted_when_none() -> None:
    result = _default(time_range_ns=None)
    # No numeric time range values should appear from a time_range line
    assert "Time Range" not in result


def test_annotations_line_when_present() -> None:
    result = _default(has_annotations=True)
    assert "annotations/" in result


def test_annotations_omitted_when_false() -> None:
    result = _default(has_annotations=False)
    assert "annotations/" not in result


GOLDEN_INPUT = {
    "bundle_name": "rec_001_20260101T120000_export",
    "recording_ids": ("rec_001",),
    "mode": "single",
    "time_range_ns": (1_000_000_000, 5_000_000_000),
    "stream_keys": ("eeg", "accel"),
    "has_annotations": True,
    "has_recording_metadata": True,
}

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "readme_golden.md"


def test_golden_match() -> None:
    actual = generate_readme(**GOLDEN_INPUT)  # type: ignore[arg-type]

    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(actual, encoding="utf-8", newline="\n")

    assert GOLDEN_PATH.exists(), (
        f"Golden file missing at {GOLDEN_PATH}. "
        "Generate it with `UPDATE_GOLDEN=1 uv run pytest packages/modlink_core/tests/test_readme.py::test_golden_match`."
    )
    expected = GOLDEN_PATH.read_text(encoding="utf-8")
    assert actual == expected, (
        "README output drifted from golden. If intentional, regenerate with UPDATE_GOLDEN=1."
    )
