from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import numpy as np


class Mp4Writer:
    """Thin wrapper around imageio-ffmpeg for writing MP4 files.

    Usage:
        Mp4Writer.write(frames, fps=30.0, output_path=Path("out.mp4"))
    """

    @staticmethod
    def write(
        frames: Iterable[np.ndarray],
        fps: float,
        output_path: Path,
    ) -> None:
        """Write frames to MP4.

        Args:
            frames: Iterable of uint8 arrays, each shape (H, W, 3) for RGB
                    or (H, W) for grayscale (will be converted to RGB)
            fps: frames per second
            output_path: destination .mp4 file path

        Raises:
            RuntimeError: if ffmpeg is not found or encoding fails
        """
        try:
            import imageio_ffmpeg
        except ImportError as e:
            raise RuntimeError(
                "imageio-ffmpeg is required for MP4 export. Install it with: uv add imageio-ffmpeg"
            ) from e

        frames_list = list(frames)
        if not frames_list:
            raise ValueError("Cannot write MP4 with zero frames")

        first = frames_list[0]
        if first.ndim == 2:
            # grayscale → convert to RGB
            frames_list = [np.stack([f, f, f], axis=-1) for f in frames_list]
            first = frames_list[0]

        h, w = first.shape[:2]

        try:
            writer = imageio_ffmpeg.write_frames(
                str(output_path),
                size=(w, h),
                fps=fps,
                codec="libx264",
                quality=5,
                pix_fmt_out="yuv420p",
            )
            writer.send(None)  # prime the generator
            for frame in frames_list:
                writer.send(frame.tobytes())
            writer.close()
        except Exception as e:
            raise RuntimeError(f"MP4 encoding failed: {e}") from e
