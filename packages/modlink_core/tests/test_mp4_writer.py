from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from modlink_core.replay.format.mp4_writer import Mp4Writer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rgb_frame(h: int = 64, w: int = 64) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def _gray_frame(h: int = 64, w: int = 64) -> np.ndarray:
    return np.zeros((h, w), dtype=np.uint8)


def _make_mock_writer() -> MagicMock:
    """Return a generator-like mock that accepts send() and close()."""
    mock = MagicMock()
    mock.send.return_value = None
    mock.close.return_value = None
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_write_calls_imageio_ffmpeg(tmp_path: Path) -> None:
    """write_frames is called with correct size and fps."""
    output = tmp_path / "out.mp4"
    frame = _rgb_frame(64, 64)
    mock_writer = _make_mock_writer()

    with patch("imageio_ffmpeg.write_frames", return_value=mock_writer) as mock_wf:
        Mp4Writer.write([frame], fps=30.0, output_path=output)

    mock_wf.assert_called_once_with(
        str(output),
        size=(64, 64),
        fps=30.0,
        codec="libx264",
        quality=5,
        pix_fmt_out="yuv420p",
    )
    # primed with None, then one frame bytes
    mock_writer.send.assert_any_call(None)
    mock_writer.close.assert_called_once()


def test_empty_frames_raises(tmp_path: Path) -> None:
    """Empty frame list raises ValueError before touching ffmpeg."""
    output = tmp_path / "out.mp4"
    with pytest.raises(ValueError, match="zero frames"):
        Mp4Writer.write([], fps=30.0, output_path=output)


def test_grayscale_converted_to_rgb(tmp_path: Path) -> None:
    """2D grayscale frame is stacked to (H, W, 3) before encoding."""
    output = tmp_path / "out.mp4"
    gray = _gray_frame(32, 48)
    mock_writer = _make_mock_writer()

    with patch("imageio_ffmpeg.write_frames", return_value=mock_writer) as mock_wf:
        Mp4Writer.write([gray], fps=24.0, output_path=output)

    # size should be (w, h) = (48, 32)
    mock_wf.assert_called_once()
    _, kwargs = mock_wf.call_args
    assert kwargs["size"] == (48, 32)

    # The bytes sent should be 3× the grayscale pixel count
    frame_bytes_call = [c for c in mock_writer.send.call_args_list if c.args[0] is not None]
    assert len(frame_bytes_call) == 1
    sent_bytes = frame_bytes_call[0].args[0]
    assert len(sent_bytes) == 32 * 48 * 3


@pytest.mark.slow
def test_real_mp4_written(tmp_path: Path) -> None:
    """Integration: write 30 real frames and verify file exists with content."""
    output = tmp_path / "test_output.mp4"
    rng = np.random.default_rng(42)
    frames = [rng.integers(0, 256, (64, 64, 3), dtype=np.uint8) for _ in range(30)]

    Mp4Writer.write(frames, fps=30.0, output_path=output)

    assert output.exists()
    assert output.stat().st_size > 0
