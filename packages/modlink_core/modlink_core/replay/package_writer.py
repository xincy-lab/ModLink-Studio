from __future__ import annotations

import shutil
import uuid
from pathlib import Path


class ExportPackageWriter:
    """Context manager that writes to a tmp directory and atomically renames on success.

    Usage:
        with ExportPackageWriter(target_dir) as pkg:
            (pkg.root / "streams").mkdir()
            write_files_into(pkg.root)
        # On exit: tmp dir renamed to target_dir

    On exception: tmp dir is cleaned up, target_dir is NOT created.
    """

    def __init__(self, target_dir: Path) -> None:
        self._target = Path(target_dir)
        self._tmp: Path | None = None

    def __enter__(self) -> ExportPackageWriter:
        tmp_name = f".tmp_{uuid.uuid4().hex}"
        self._tmp = self._target.parent / tmp_name
        self._tmp.mkdir(parents=True, exist_ok=False)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is None:
            # Success: atomic rename
            # Handle collision: if target already exists, append _2, _3, ...
            target = self._target
            if target.exists():
                n = 2
                while True:
                    candidate = target.parent / f"{target.name}_{n}"
                    if not candidate.exists():
                        target = candidate
                        break
                    n += 1
            # Path.rename() fails on Windows when target exists, but we've
            # already ensured target doesn't exist above. Use shutil.move as
            # a cross-filesystem fallback.
            try:
                self._tmp.rename(target)
            except OSError:
                shutil.move(str(self._tmp), str(target))
            self._target = target  # update so caller can read final path
        else:
            # Failure: clean up tmp
            if self._tmp and self._tmp.exists():
                shutil.rmtree(self._tmp)
        return False  # don't suppress exceptions

    @property
    def root(self) -> Path:
        """The directory to write into (the tmp dir during context)."""
        if self._tmp is None:
            raise RuntimeError("ExportPackageWriter must be used as a context manager")
        return self._tmp

    @property
    def final_path(self) -> Path:
        """The final target path (only valid after __exit__ succeeds)."""
        return self._target
