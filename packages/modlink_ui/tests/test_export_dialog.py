from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shutil
import sys
import unittest
from pathlib import Path
from uuid import uuid4

import numpy as np

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

from PyQt6.QtWidgets import QApplication, QWidget

from modlink_core.replay.export_request import ExportMode
from modlink_core.storage import append_recording_frame, create_recording
from modlink_sdk import FrameEnvelope, StreamDescriptor
from modlink_ui.features.replay.export_dialog import ExportDialog


class ExportDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        test_tmp_root = WORKSPACE_ROOT / ".tmp-tests"
        test_tmp_root.mkdir(exist_ok=True)
        self._temp_dir = test_tmp_root / f"export-dialog-{uuid4().hex}"
        self._temp_dir.mkdir()
        self._parent = QWidget()

    def tearDown(self) -> None:
        self._parent.deleteLater()
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_recording(self, stream_key: str = "signal", payload_type: str = "signal") -> str:
        descriptor = StreamDescriptor(
            device_id="demo.01",
            stream_key=stream_key,
            payload_type=payload_type,
            nominal_sample_rate_hz=20.0,
            chunk_size=2,
            channel_names=("c1", "c2"),
            display_name="Test",
        )
        recording_id = create_recording(self._temp_dir, {descriptor.stream_id: descriptor})
        append_recording_frame(
            self._temp_dir,
            recording_id,
            FrameEnvelope(
                device_id="demo.01",
                stream_key=stream_key,
                timestamp_ns=1_000_000_000,
                data=np.zeros((2, 2), dtype=np.float32),
                seq=1,
            ),
            frame_index=1,
        )
        return recording_id

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_dialog_constructs_with_single_recording(self) -> None:
        rec_id = self._make_recording()
        dialog = ExportDialog([rec_id], self._temp_dir, parent=self._parent)
        self.assertIsNotNone(dialog)
        self.assertEqual(len(dialog._stream_rows), 1)

    def test_dialog_constructs_with_multiple_recordings(self) -> None:
        rec1 = self._make_recording(stream_key="signal")
        rec2 = self._make_recording(stream_key="accel")
        dialog = ExportDialog([rec1, rec2], self._temp_dir, parent=self._parent)
        self.assertIsNotNone(dialog)
        self.assertEqual(len(dialog._stream_rows), 2)

    def test_build_request_returns_none_when_no_streams_checked(self) -> None:
        rec_id = self._make_recording()
        dialog = ExportDialog([rec_id], self._temp_dir, parent=self._parent)
        for _, cb, _ in dialog._stream_rows:
            cb.setChecked(False)
        self.assertIsNone(dialog.build_request())

    def test_build_request_returns_valid_request_single_mode(self) -> None:
        rec_id = self._make_recording()
        dialog = ExportDialog([rec_id], self._temp_dir, parent=self._parent)
        request = dialog.build_request()
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.mode, ExportMode.SINGLE)
        self.assertEqual(request.recording_ids, (rec_id,))
        self.assertIsNone(request.time_range_ns)
        self.assertEqual(len(request.streams), 1)

    def test_build_request_returns_timeslice_when_time_range_set(self) -> None:
        rec_id = self._make_recording()
        dialog = ExportDialog([rec_id], self._temp_dir, parent=self._parent)
        dialog._time_range_enabled.setChecked(True)
        dialog._time_start_edit.setText("00:00:01.000")
        dialog._time_end_edit.setText("00:00:05.000")
        request = dialog.build_request()
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.mode, ExportMode.TIMESLICE)
        self.assertEqual(request.time_range_ns, (1_000_000_000, 5_000_000_000))

    def test_build_request_returns_multi_mode_for_multiple_recordings(self) -> None:
        rec1 = self._make_recording(stream_key="signal")
        rec2 = self._make_recording(stream_key="accel")
        dialog = ExportDialog([rec1, rec2], self._temp_dir, parent=self._parent)
        request = dialog.build_request()
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.mode, ExportMode.MULTI)
        self.assertEqual(len(request.recording_ids), 2)

    def test_time_range_section_hidden_for_multi(self) -> None:
        rec1 = self._make_recording(stream_key="signal")
        rec2 = self._make_recording(stream_key="accel")
        dialog = ExportDialog([rec1, rec2], self._temp_dir, parent=self._parent)
        # For multi, the time range checkbox exists but the card is never added
        # to viewLayout — verify the checkbox is not checked and time range has no effect
        dialog._time_range_enabled.setChecked(True)
        dialog._time_start_edit.setText("00:00:01.000")
        dialog._time_end_edit.setText("00:00:05.000")
        request = dialog.build_request()
        assert request is not None
        # Even with time range "enabled", multi mode ignores it
        self.assertEqual(request.mode, ExportMode.MULTI)
        self.assertIsNone(request.time_range_ns)

    def test_time_range_section_visible_for_single(self) -> None:
        rec_id = self._make_recording()
        dialog = ExportDialog([rec_id], self._temp_dir, parent=self._parent)
        # For single recording, the time range checkbox is accessible and functional
        self.assertFalse(dialog._time_range_enabled.isChecked())
        dialog._time_range_enabled.setChecked(True)
        self.assertTrue(dialog._time_range_enabled.isChecked())


if __name__ == "__main__":
    unittest.main()
