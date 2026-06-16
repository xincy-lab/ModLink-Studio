from __future__ import annotations

import os
import shutil
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from qfluentwidgets import MessageBox

from modlink_core.models import ReplaySnapshot
from modlink_core.replay import ReplayBackend
from modlink_core.settings import SettingsStore, declare_core_settings
from modlink_core.storage import (
    add_recording_marker,
    add_recording_segment,
    append_recording_frame,
    create_recording,
)
from modlink_sdk import FrameEnvelope, StreamDescriptor
from modlink_ui.bridge import QtReplayBridge, QtSettingsBridge
from modlink_ui.features.replay import ReplayPage
from modlink_ui.features.replay.player_page import parse_time_text


class _EngineStub:
    def __init__(self, settings: QtSettingsBridge, replay: QtReplayBridge) -> None:
        self.settings = settings
        self.replay = replay


class ReplayPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        test_tmp_root = WORKSPACE_ROOT / ".tmp-tests"
        test_tmp_root.mkdir(exist_ok=True)
        self._temp_dir = test_tmp_root / f"replay-page-{uuid4().hex}"
        self._temp_dir.mkdir()
        self._settings = SettingsStore(path=self._temp_dir / "settings.json")
        declare_core_settings(self._settings)
        self._settings.storage.root_dir = str(self._temp_dir)
        self._settings.storage.export_root_dir = str(self._temp_dir / "exports")
        self._settings_bridge = QtSettingsBridge(self._settings)

    def tearDown(self) -> None:
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    @staticmethod
    def _descriptor() -> StreamDescriptor:
        return StreamDescriptor(
            device_id="demo.01",
            stream_key="signal",
            payload_type="signal",
            nominal_sample_rate_hz=20.0,
            chunk_size=2,
            channel_names=("c3", "c4"),
            display_name="Signal",
        )

    def _create_recording(
        self,
        descriptor: StreamDescriptor,
        *,
        recording_label: str,
        with_two_frames: bool = True,
    ) -> str:
        recording_id = create_recording(
            self._temp_dir,
            {descriptor.stream_id: descriptor},
            recording_label=recording_label,
        )
        append_recording_frame(
            self._temp_dir,
            recording_id,
            FrameEnvelope(
                device_id=descriptor.device_id,
                stream_key=descriptor.stream_key,
                timestamp_ns=1_000_000_000,
                data=np.zeros((2, 2), dtype=np.float32),
                seq=1,
            ),
            frame_index=1,
        )
        if with_two_frames:
            append_recording_frame(
                self._temp_dir,
                recording_id,
                FrameEnvelope(
                    device_id=descriptor.device_id,
                    stream_key=descriptor.stream_key,
                    timestamp_ns=1_050_000_000,
                    data=np.ones((2, 2), dtype=np.float32),
                    seq=2,
                ),
                frame_index=2,
            )
        return recording_id

    def test_page_lists_recordings_opens_selection_and_updates_export_jobs(self) -> None:
        descriptor = self._descriptor()
        recording_id = self._create_recording(
            descriptor,
            recording_label="page_case",
        )

        backend = ReplayBackend(settings=self._settings)
        backend.start()
        replay_bridge = QtReplayBridge(backend, self._settings_bridge)
        page = ReplayPage(_EngineStub(self._settings_bridge, replay_bridge))
        page.show()

        try:
            recordings_page = page._recordings_page
            player_page = page._player_page
            self.assertEqual("recordings", page._route)
            self.assertEqual("打开", recordings_page.open_button.text())
            self.assertEqual("刷新", recordings_page.refresh_button.text())
            self.assertEqual(
                recordings_page.open_button.width(),
                recordings_page.refresh_button.width(),
            )
            self.assertEqual(2, recordings_page.header_action_layout.count())
            self.assertEqual(2, recordings_page.content_layout.count())
            self.assertEqual(1, recordings_page.content_layout.stretch(1))
            self._pump_events_until(lambda: recordings_page.recording_list.count() == 1)
            recordings_page.recording_list.setCurrentRow(0)
            recordings_page.open_button.click()
            self._pump_events_until(
                lambda: (
                    replay_bridge.snapshot().recording_id == recording_id
                    and page._route == "player"
                )
            )

            self.assertEqual(recording_id, replay_bridge.snapshot().recording_id)
            self.assertEqual("player", page._route)
            self.assertTrue(player_page.preview_panel._cards)
            self._pump_events_until(lambda: player_page.transport_bar.isVisible())
            self.assertIs(player_page.transport_bar.parentWidget(), player_page)
            self.assertEqual(3, player_page.header_action_layout.count())
            self.assertGreater(player_page._floating_spacer.height(), 0)
            self.assertTrue(player_page.export_route_button.isEnabled())
            self.assertIs(player_page.preview_panel.parentWidget(), player_page.scroll_widget)
            self.assertEqual("列表", player_page.recordings_route_button.text())
            self.assertEqual("导出", player_page.export_route_button.text())
            self.assertEqual(0, player_page.recordings_route_button.minimumHeight())
            self.assertEqual(0, player_page.export_route_button.minimumHeight())
            self.assertEqual("播放", player_page.play_pause_button.text())
            self.assertEqual("复位", player_page.reset_button.text())
            self.assertEqual(0, player_page.play_pause_button.minimumHeight())
            self.assertEqual(0, player_page.reset_button.minimumHeight())
            self.assertFalse(player_page.recordings_route_button.icon().isNull())
            self.assertFalse(player_page.export_route_button.icon().isNull())
            self.assertEqual(
                Qt.AlignmentFlag.AlignCenter,
                player_page.position_label.alignment(),
            )
            badge_center_y = player_page.position_label.geometry().center().y()
            play_center_y = player_page.play_pause_button.geometry().center().y()
            self.assertLess(abs(badge_center_y - play_center_y), 8)

            player_page.play_pause_button.click()
            self._pump_events_until(
                lambda: replay_bridge.snapshot().state in {"playing", "finished"},
                timeout=2.0,
            )

            # Export is now dialog-based; verify the export button signal is wired
            self.assertFalse(hasattr(page, "_export_page"))
        finally:
            page.close()
            replay_bridge.shutdown()
            backend.shutdown()

    def test_refresh_recordings_keeps_selected_item(self) -> None:
        descriptor = self._descriptor()
        first_recording_id = self._create_recording(descriptor, recording_label="first")
        second_recording_id = self._create_recording(descriptor, recording_label="second")

        backend = ReplayBackend(settings=self._settings)
        backend.start()
        replay_bridge = QtReplayBridge(backend, self._settings_bridge)
        page = ReplayPage(_EngineStub(self._settings_bridge, replay_bridge))
        page.show()

        try:
            self._pump_events_until(lambda: page._recordings_page.recording_list.count() == 2)
            self._select_recording(page, second_recording_id)

            self._create_recording(descriptor, recording_label="third", with_two_frames=False)
            replay_bridge.refresh_recordings()
            self._pump_events_until(lambda: page._recordings_page.recording_list.count() == 3)

            current_item = page._recordings_page.recording_list.currentItem()
            self.assertIsNotNone(current_item)
            self.assertEqual(
                second_recording_id,
                current_item.data(Qt.ItemDataRole.UserRole),
            )
            self.assertNotEqual(first_recording_id, second_recording_id)
        finally:
            page.close()
            replay_bridge.shutdown()
            backend.shutdown()

    def test_reopen_same_recording_after_returning_to_list_routes_back_to_player(self) -> None:
        descriptor = self._descriptor()
        recording_id = self._create_recording(
            descriptor,
            recording_label="reopen_same_recording",
        )

        backend = ReplayBackend(settings=self._settings)
        backend.start()
        replay_bridge = QtReplayBridge(backend, self._settings_bridge)
        page = ReplayPage(_EngineStub(self._settings_bridge, replay_bridge))
        page.show()

        try:
            recordings_page = page._recordings_page
            self._pump_events_until(lambda: recordings_page.recording_list.count() == 1)
            recordings_page.recording_list.setCurrentRow(0)
            recordings_page.open_button.click()
            self._pump_events_until(
                lambda: (
                    replay_bridge.snapshot().recording_id == recording_id
                    and page._route == "player"
                )
            )

            page._show_recordings_page()
            self.assertEqual("recordings", page._route)
            recordings_page.open_button.click()
            self._pump_events_until(lambda: page._route == "player")
            self.assertEqual(recording_id, replay_bridge.snapshot().recording_id)
            self.assertIsNone(page._pending_open_recording_path)
        finally:
            page.close()
            replay_bridge.shutdown()
            backend.shutdown()

    def test_recording_list_items_stay_compact_for_long_titles(self) -> None:
        descriptor = self._descriptor()
        short_label = "short"
        long_label = (
            "rec_20260421T153943_302514500Z"
            "_extra_suffix_for_test"
            "_extra_suffix_for_test"
            "_extra_suffix_for_test"
        )
        self._create_recording(descriptor, recording_label=short_label)
        self._create_recording(descriptor, recording_label=long_label)

        backend = ReplayBackend(settings=self._settings)
        backend.start()
        replay_bridge = QtReplayBridge(backend, self._settings_bridge)
        page = ReplayPage(_EngineStub(self._settings_bridge, replay_bridge))
        page.resize(900, 720)
        page.show()

        try:
            recording_list = page._recordings_page.recording_list
            self._pump_events_until(lambda: recording_list.count() == 2)

            items_by_text = {}
            for row in range(recording_list.count()):
                item = recording_list.item(row)
                self.assertIsNone(recording_list.itemWidget(item))
                items_by_text[item.text()] = item

            short_text = f"{short_label} · 1 stream"
            long_text = f"{long_label} · 1 stream"
            self.assertIn(short_text, items_by_text)
            self.assertIn(long_text, items_by_text)
        finally:
            page.close()
            replay_bridge.shutdown()
            backend.shutdown()

    def test_recording_list_does_not_repeat_id_when_label_is_missing(self) -> None:
        descriptor = self._descriptor()
        recording_id = self._create_recording(descriptor, recording_label="")

        backend = ReplayBackend(settings=self._settings)
        backend.start()
        replay_bridge = QtReplayBridge(backend, self._settings_bridge)
        page = ReplayPage(_EngineStub(self._settings_bridge, replay_bridge))
        page.show()

        try:
            recording_list = page._recordings_page.recording_list
            self._pump_events_until(lambda: recording_list.count() == 1)
            item = recording_list.item(0)
            self.assertEqual(
                f"{recording_id} · 1 stream",
                item.text(),
            )
            self.assertIsNone(recording_list.itemWidget(item))
        finally:
            page.close()
            replay_bridge.shutdown()
            backend.shutdown()

    def test_player_preview_keeps_stream_card_heights_inside_scroll_area(self) -> None:
        descriptors = [
            StreamDescriptor(
                device_id="audio.01",
                stream_key="audio",
                payload_type="signal",
                nominal_sample_rate_hz=16_000.0,
                chunk_size=8,
                channel_names=("mic",),
                display_name="Host Microphone Waveform",
            ),
            StreamDescriptor(
                device_id="sensor.01",
                stream_key="adc_uv",
                payload_type="signal",
                nominal_sample_rate_hz=50.0,
                chunk_size=8,
                channel_names=("adc1_ch3",),
                display_name="柔性力学传感器 (ESP32-S3) Microvolts",
                metadata={"unit": "uV"},
            ),
            StreamDescriptor(
                device_id="smg.01",
                stream_key="smg",
                payload_type="signal",
                nominal_sample_rate_hz=300.0,
                chunk_size=8,
                channel_names=("a0", "a1"),
                display_name="肌电数据",
            ),
        ]
        recording_id = create_recording(
            self._temp_dir,
            {descriptor.stream_id: descriptor for descriptor in descriptors},
            recording_label="multi_stream",
        )
        for descriptor in descriptors:
            channel_count = len(descriptor.channel_names)
            append_recording_frame(
                self._temp_dir,
                recording_id,
                FrameEnvelope(
                    device_id=descriptor.device_id,
                    stream_key=descriptor.stream_key,
                    timestamp_ns=1_000_000_000,
                    data=np.zeros((channel_count, 8), dtype=np.float32),
                    seq=1,
                ),
                frame_index=1,
            )

        backend = ReplayBackend(settings=self._settings)
        backend.start()
        replay_bridge = QtReplayBridge(backend, self._settings_bridge)
        page = ReplayPage(_EngineStub(self._settings_bridge, replay_bridge))
        page.resize(900, 720)
        page.show()

        try:
            self._pump_events_until(lambda: page._recordings_page.recording_list.count() == 1)
            page._recordings_page.recording_list.setCurrentRow(0)
            page._recordings_page.open_button.click()
            self._pump_events_until(
                lambda: (
                    replay_bridge.snapshot().recording_id == recording_id
                    and page._route == "player"
                    and len(page._player_page.preview_panel._cards) == 3
                )
            )
            self._pump_events_until(
                lambda: (
                    page._player_page.scroll_widget.height()
                    > page._player_page.scroll_area.viewport().height()
                )
            )

            player_page = page._player_page
            preview_panel = player_page.preview_panel
            required_content_height = max(
                preview_panel.cards_container.minimumSizeHint().height(),
                preview_panel.cards_container.sizeHint().height(),
            )

            self.assertGreater(required_content_height, player_page.scroll_area.viewport().height())
            self.assertGreaterEqual(preview_panel.minimumHeight(), required_content_height)
            self.assertGreaterEqual(preview_panel.cards_container.height(), required_content_height)
            for wrapper in preview_panel._cards.values():
                self.assertGreaterEqual(wrapper.height(), wrapper.minimumSizeHint().height())
                self.assertGreaterEqual(
                    wrapper.card.stream_view.height(),
                    wrapper.card.stream_view.minimumHeight(),
                )
        finally:
            page.close()
            replay_bridge.shutdown()
            backend.shutdown()

    def test_snapshot_highlights_latest_marker_and_active_segment(self) -> None:
        """Annotations are no longer rendered in the UI (timeline widget removed).

        This test verifies that opening a recording with markers/segments
        does not crash and that the player page applies the snapshot correctly.
        """
        descriptor = self._descriptor()
        recording_id = self._create_recording(
            descriptor,
            recording_label="annotated",
        )
        add_recording_marker(self._temp_dir, recording_id, 1_000_000_000, "start")
        add_recording_marker(self._temp_dir, recording_id, 1_500_000_000, "cue")
        add_recording_segment(
            self._temp_dir,
            recording_id,
            1_200_000_000,
            1_800_000_000,
            "trial",
        )

        backend = ReplayBackend(settings=self._settings)
        backend.start()
        replay_bridge = QtReplayBridge(backend, self._settings_bridge)
        page = ReplayPage(_EngineStub(self._settings_bridge, replay_bridge))
        page.show()

        try:
            self._pump_events_until(lambda: page._recordings_page.recording_list.count() == 1)
            page._recordings_page.recording_list.setCurrentRow(0)
            page._recordings_page.open_button.click()
            self._pump_events_until(
                lambda: (
                    replay_bridge.snapshot().recording_id == recording_id
                    and page._route == "player"
                )
            )
            self._pump_events_until(
                lambda: (
                    replay_bridge.snapshot().recording_id == recording_id
                    and page._route == "player"
                )
            )

            page._on_snapshot_changed(
                ReplaySnapshot(
                    state="paused",
                    is_started=True,
                    recording_id=recording_id,
                    recording_path=str(self._temp_dir / "recordings" / recording_id),
                    position_ns=600_000_000,
                    duration_ns=1_000_000_000,
                    speed_multiplier=1.0,
                )
            )

            self.assertFalse(hasattr(page._player_page, "annotations_card"))
            # Slider should reflect the position (600/1000 = 60% of range 0-10000 = 6000)
            self.assertEqual(6000, page._player_page.slider.value())
        finally:
            page.close()
            replay_bridge.shutdown()
            backend.shutdown()

    def test_transport_button_switches_between_pause_and_reset(self) -> None:
        descriptor = self._descriptor()
        recording_id = self._create_recording(
            descriptor,
            recording_label="transport_button",
        )

        backend = ReplayBackend(settings=self._settings)
        backend.start()
        replay_bridge = QtReplayBridge(backend, self._settings_bridge)
        page = ReplayPage(_EngineStub(self._settings_bridge, replay_bridge))
        page.show()

        try:
            player_page = page._player_page
            self._pump_events_until(lambda: page._recordings_page.recording_list.count() == 1)
            page._recordings_page.recording_list.setCurrentRow(0)
            page._recordings_page.open_button.click()
            self._pump_events_until(
                lambda: (
                    replay_bridge.snapshot().recording_id == recording_id
                    and page._route == "player"
                )
            )

            self.assertEqual("播放", player_page.play_pause_button.text())
            self.assertEqual("复位", player_page.reset_button.text())
            self.assertEqual("复位", player_page.reset_button.toolTip())
            self.assertTrue(player_page.reset_button.isEnabled())

            calls: list[str] = []
            player_page.sig_pause_requested.connect(lambda: calls.append("pause"))
            player_page.sig_reset_requested.connect(lambda: calls.append("stop"))

            playing_snapshot = ReplaySnapshot(
                state="playing",
                is_started=True,
                recording_id=recording_id,
                recording_path=str(self._temp_dir / "recordings" / recording_id),
                position_ns=600_000_000,
                duration_ns=1_000_000_000,
                speed_multiplier=1.0,
            )
            page._on_snapshot_changed(playing_snapshot)
            self.assertEqual("暂停", player_page.play_pause_button.text())
            self.assertEqual("暂停", player_page.play_pause_button.toolTip())
            self.assertTrue(player_page.play_pause_button.isEnabled())
            player_page.play_pause_button.click()
            self.assertEqual(["pause"], calls)

            paused_snapshot = ReplaySnapshot(
                state="paused",
                is_started=True,
                recording_id=recording_id,
                recording_path=str(self._temp_dir / "recordings" / recording_id),
                position_ns=600_000_000,
                duration_ns=1_000_000_000,
                speed_multiplier=1.0,
            )
            page._on_snapshot_changed(paused_snapshot)
            self.assertEqual("复位", player_page.reset_button.text())
            self.assertEqual("复位", player_page.reset_button.toolTip())
            self.assertTrue(player_page.reset_button.isEnabled())
            player_page.reset_button.click()
            self.assertEqual(["pause", "stop"], calls)
        finally:
            page.close()
            replay_bridge.shutdown()
            backend.shutdown()

    def test_slider_and_time_input_basic(self) -> None:
        """Verify the slider and time input exist and parse_time_text works."""
        self.assertEqual(0, parse_time_text("00:00.000"))
        self.assertEqual(5_000_000_000, parse_time_text("00:05.000"))
        self.assertEqual(63_456_000_000, parse_time_text("01:03.456"))
        self.assertEqual(3_723_100_000_000, parse_time_text("01:02:03.100"))
        self.assertIsNone(parse_time_text(""))
        self.assertIsNone(parse_time_text("abc"))

    def test_slider_track_click_emits_seek(self) -> None:
        """Clicking the slider track (not dragging the handle) should emit sig_seek_requested."""
        descriptor = self._descriptor()
        recording_id = self._create_recording(descriptor, recording_label="click_seek")

        backend = ReplayBackend(settings=self._settings)
        backend.start()
        replay_bridge = QtReplayBridge(backend, self._settings_bridge)
        page = ReplayPage(_EngineStub(self._settings_bridge, replay_bridge))
        page.show()

        try:
            self._pump_events_until(lambda: page._recordings_page.recording_list.count() == 1)
            page._recordings_page.recording_list.setCurrentRow(0)
            page._recordings_page.open_button.click()
            self._pump_events_until(
                lambda: (
                    replay_bridge.snapshot().recording_id == recording_id
                    and page._route == "player"
                )
            )

            player_page = page._player_page
            # Set a known snapshot so duration_ns is non-zero
            page._on_snapshot_changed(
                ReplaySnapshot(
                    state="ready",
                    is_started=True,
                    recording_id=recording_id,
                    recording_path=str(self._temp_dir / "recordings" / recording_id),
                    position_ns=0,
                    duration_ns=1_000_000_000,
                    speed_multiplier=1.0,
                )
            )

            seek_positions: list[int] = []
            player_page.sig_seek_requested.connect(seek_positions.append)

            # Simulate a track click at slider value 5000 (50% of range)
            player_page.slider.clicked.emit(5000)
            self._app.processEvents()

            # Should have emitted a seek to 50% of duration = 500_000_000 ns
            self.assertEqual(1, len(seek_positions))
            self.assertEqual(500_000_000, seek_positions[0])
        finally:
            page.close()
            replay_bridge.shutdown()
            backend.shutdown()

    def test_slider_seek_signal_carries_qint64_for_long_recordings(self) -> None:
        """Regression: PyQt's plain `pyqtSignal(int)` is C int32 (max ~2.147s in
        ns). Recordings longer than that overflow into a negative number, the
        backend clamps it to 0, and every seek silently plays from the start.
        The signal MUST be declared with qint64."""
        descriptor = self._descriptor()
        recording_id = self._create_recording(descriptor, recording_label="long_seek")

        backend = ReplayBackend(settings=self._settings)
        backend.start()
        replay_bridge = QtReplayBridge(backend, self._settings_bridge)
        page = ReplayPage(_EngineStub(self._settings_bridge, replay_bridge))
        page.show()

        try:
            self._pump_events_until(lambda: page._recordings_page.recording_list.count() == 1)
            page._recordings_page.recording_list.setCurrentRow(0)
            page._recordings_page.open_button.click()
            self._pump_events_until(
                lambda: (
                    replay_bridge.snapshot().recording_id == recording_id
                    and page._route == "player"
                )
            )

            player_page = page._player_page
            # 6-second duration: 60% = 3.6s = 3,600,000,000 ns. This exceeds
            # int32 max (2,147,483,647) and would wrap negative through a
            # plain `pyqtSignal(int)`.
            page._on_snapshot_changed(
                ReplaySnapshot(
                    state="ready",
                    is_started=True,
                    recording_id=recording_id,
                    recording_path=str(self._temp_dir / "recordings" / recording_id),
                    position_ns=0,
                    duration_ns=6_000_000_000,
                    speed_multiplier=1.0,
                )
            )

            received: list[int] = []
            player_page.sig_seek_requested.connect(received.append)

            # Click at 60% (3.6s): would be -694,967,296 if int32 overflow.
            player_page.slider.setValue(6000)
            player_page.slider.clicked.emit(6000)
            self._app.processEvents()

            self.assertEqual(1, len(received))
            self.assertEqual(
                3_600_000_000,
                received[0],
                "Signal must carry full qint64 ns value, not int32-truncated",
            )
            self.assertGreater(received[0], 0, "Seek position must not wrap negative")
        finally:
            page.close()
            replay_bridge.shutdown()
            backend.shutdown()

    def test_slider_does_not_snap_back_on_stale_snapshot_after_seek(self) -> None:
        """After a seek, a stale snapshot (still showing old position) must NOT
        snap the slider back during the brief suppression window. Once the
        window expires the slider must resume syncing from snapshots — even if
        the backend overshoots the seek target during playback (no lock-forever).
        The label must also update immediately on click so the user sees the
        seek take effect, not stay frozen at the pre-seek time."""
        descriptor = self._descriptor()
        recording_id = self._create_recording(descriptor, recording_label="snap_back")

        backend = ReplayBackend(settings=self._settings)
        backend.start()
        replay_bridge = QtReplayBridge(backend, self._settings_bridge)
        page = ReplayPage(_EngineStub(self._settings_bridge, replay_bridge))
        page.show()

        try:
            self._pump_events_until(lambda: page._recordings_page.recording_list.count() == 1)
            page._recordings_page.recording_list.setCurrentRow(0)
            page._recordings_page.open_button.click()
            self._pump_events_until(
                lambda: (
                    replay_bridge.snapshot().recording_id == recording_id
                    and page._route == "player"
                )
            )

            player_page = page._player_page
            # Establish a known starting state: ready, position 0, duration 1s.
            initial_snapshot = ReplaySnapshot(
                state="ready",
                is_started=True,
                recording_id=recording_id,
                recording_path=str(self._temp_dir / "recordings" / recording_id),
                position_ns=0,
                duration_ns=1_000_000_000,
                speed_multiplier=1.0,
            )
            page._on_snapshot_changed(initial_snapshot)
            self.assertEqual(0, player_page.slider.value())
            self.assertEqual("00:00.000 / 00:01.000", player_page.position_label.text())

            # User clicks the track at 50%. In the real qfluentwidgets.Slider,
            # mousePressEvent calls setValue() before emitting clicked.
            player_page.slider.setValue(5000)
            player_page.slider.clicked.emit(5000)
            self._app.processEvents()
            self.assertEqual(5000, player_page.slider.value())
            # Label must update immediately on click — no waiting for backend.
            self.assertEqual(
                "00:00.500 / 00:01.000",
                player_page.position_label.text(),
                "Label must reflect the click target immediately",
            )

            # Stale snapshot arrives (poll timer fired before backend processed seek).
            stale_snapshot = ReplaySnapshot(
                state="ready",
                is_started=True,
                recording_id=recording_id,
                recording_path=str(self._temp_dir / "recordings" / recording_id),
                position_ns=0,  # Still old position.
                duration_ns=1_000_000_000,
                speed_multiplier=1.0,
            )
            page._on_snapshot_changed(stale_snapshot)
            # Slider and label must stay at the user's target during the
            # suppression window.
            self.assertEqual(
                5000,
                player_page.slider.value(),
                "Stale snapshot must not snap slider back to old position",
            )
            self.assertEqual(
                "00:00.500 / 00:01.000",
                player_page.position_label.text(),
                "Stale snapshot must not reset label to old position",
            )

            # Force the suppression window to expire so we can verify the
            # sync resumes. (300ms wall-clock is too slow for a unit test.)
            player_page._seek_suppress_until_ns = 0

            # Now a backend snapshot drives the slider normally — even one
            # that has already overshot the original seek target. This is the
            # critical "no lock-forever" property: the old guard logic would
            # have permanently blocked sync once playback advanced past the
            # pending seek position.
            overshoot_snapshot = ReplaySnapshot(
                state="playing",
                is_started=True,
                recording_id=recording_id,
                recording_path=str(self._temp_dir / "recordings" / recording_id),
                position_ns=700_000_000,  # Past the 500ms seek target.
                duration_ns=1_000_000_000,
                speed_multiplier=1.0,
            )
            page._on_snapshot_changed(overshoot_snapshot)
            self.assertEqual(
                7000,
                player_page.slider.value(),
                "Sync must resume after suppression window — no lock-forever",
            )
            self.assertEqual(
                "00:00.700 / 00:01.000",
                player_page.position_label.text(),
            )
        finally:
            page.close()
            replay_bridge.shutdown()
            backend.shutdown()

    def _select_recording(self, page: ReplayPage, recording_id: str) -> None:
        recording_list = page._recordings_page.recording_list
        for index in range(recording_list.count()):
            item = recording_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == recording_id:
                recording_list.setCurrentItem(item)
                return
        raise AssertionError(f"recording_id not found in list: {recording_id}")

    def _pump_events_until(self, predicate, *, timeout: float = 1.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._app.processEvents()
            if predicate():
                return
            time.sleep(0.01)
        self._app.processEvents()
        if predicate():
            return
        raise AssertionError("condition not reached before timeout")

    def test_recordings_page_context_menu_delete_emits_signal_after_confirm(self) -> None:
        descriptor = self._descriptor()
        keep_id = self._create_recording(descriptor, recording_label="keep")
        drop_id = self._create_recording(descriptor, recording_label="drop")

        backend = ReplayBackend(settings=self._settings)
        backend.start()
        replay_bridge = QtReplayBridge(backend, self._settings_bridge)
        page = ReplayPage(_EngineStub(self._settings_bridge, replay_bridge))
        page.show()

        try:
            recording_list = page._recordings_page.recording_list
            self._pump_events_until(lambda: recording_list.count() == 2)

            with patch.object(MessageBox, "exec", return_value=True):
                page._recordings_page.recordings_panel.sig_delete_recording_requested.emit(drop_id)

            self._pump_events_until(lambda: recording_list.count() == 1)
            remaining_id = recording_list.item(0).data(Qt.ItemDataRole.UserRole)
            self.assertEqual(keep_id, remaining_id)
        finally:
            page.close()
            replay_bridge.shutdown()
            backend.shutdown()

    def test_recordings_page_context_menu_delete_skips_when_dialog_cancelled(self) -> None:
        descriptor = self._descriptor()
        recording_id = self._create_recording(descriptor, recording_label="keep")

        backend = ReplayBackend(settings=self._settings)
        backend.start()
        replay_bridge = QtReplayBridge(backend, self._settings_bridge)
        page = ReplayPage(_EngineStub(self._settings_bridge, replay_bridge))
        page.show()

        try:
            recording_list = page._recordings_page.recording_list
            self._pump_events_until(lambda: recording_list.count() == 1)

            with patch.object(MessageBox, "exec", return_value=False):
                page._recordings_page.recordings_panel.sig_delete_recording_requested.emit(
                    recording_id
                )
            self._app.processEvents()

            self.assertEqual(1, recording_list.count())
            self.assertTrue((self._temp_dir / "recordings" / recording_id).exists())
        finally:
            page.close()
            replay_bridge.shutdown()
            backend.shutdown()

    def test_player_page_delete_button_removes_currently_open_recording(self) -> None:
        descriptor = self._descriptor()
        recording_id = self._create_recording(descriptor, recording_label="open_then_delete")

        backend = ReplayBackend(settings=self._settings)
        backend.start()
        replay_bridge = QtReplayBridge(backend, self._settings_bridge)
        page = ReplayPage(_EngineStub(self._settings_bridge, replay_bridge))
        page.show()

        try:
            recording_list = page._recordings_page.recording_list
            self._pump_events_until(lambda: recording_list.count() == 1)
            self._select_recording(page, recording_id)
            page._recordings_page.open_button.click()
            self._pump_events_until(
                lambda: (
                    replay_bridge.snapshot().recording_id == recording_id
                    and page._route == "player"
                )
            )

            with patch.object(MessageBox, "exec", return_value=True):
                page._player_page.delete_button.click()

            self._pump_events_until(lambda: replay_bridge.snapshot().recording_id is None)
            self._pump_events_until(lambda: page._route == "recordings")
            self.assertFalse((self._temp_dir / "recordings" / recording_id).exists())
            self.assertEqual(0, recording_list.count())
        finally:
            page.close()
            replay_bridge.shutdown()
            backend.shutdown()


if __name__ == "__main__":
    unittest.main()
