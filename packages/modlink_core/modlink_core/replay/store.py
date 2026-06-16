from __future__ import annotations

from pathlib import Path

from .reader import RecordingReader


class RecordingStore:
    def __init__(self, root_dir: Path) -> None:
        self._root = Path(root_dir)

    def list_recording_ids(self) -> tuple[str, ...]:
        """Scan <root>/recordings/* subdirectories, return their names as IDs."""
        recordings_dir = self._root / "recordings"
        if not recordings_dir.exists():
            return ()
        return tuple(p.name for p in sorted(recordings_dir.iterdir()) if p.is_dir())

    def open(self, recording_id: str) -> RecordingReader:
        """Open a RecordingReader for the given recording_id."""
        recording_path = self._root / "recordings" / recording_id
        return RecordingReader(recording_path)

    def find_recordings_with_stream(self, stream_key: str) -> tuple[str, ...]:
        """Return recording IDs that contain at least one stream with the given stream_key."""
        result = []
        for rec_id in self.list_recording_ids():
            reader = self.open(rec_id)
            for desc in reader.descriptors().values():
                if desc.stream_key == stream_key:
                    result.append(rec_id)
                    break
        return tuple(result)
