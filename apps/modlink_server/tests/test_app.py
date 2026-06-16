from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from modlink_server.app import create_app, main
from modlink_server.routes import _iter_sse_messages

from modlink_core import EventStreamOverflowError, SettingsStore
from modlink_core.settings import SettingsGroup, SettingsStr
from modlink_sdk import Driver, FrameEnvelope, SearchResult, StreamDescriptor


class ApiDemoDriver(Driver):
    supported_providers = ("demo",)

    def __init__(self, device_id: str = "api_demo.01") -> None:
        super().__init__()
        self._device_id = device_id
        self.connected = False
        self.streaming = False
        self.shutdown_called = False

    @property
    def device_id(self) -> str:
        return self._device_id

    def descriptors(self) -> list[StreamDescriptor]:
        return [
            StreamDescriptor(
                device_id=self.device_id,
                stream_key="demo",
                payload_type="signal",
                nominal_sample_rate_hz=10.0,
                chunk_size=4,
                channel_names=("demo",),
            )
        ]

    def search(self, provider: str) -> list[SearchResult]:
        if provider != "demo":
            raise ValueError("unsupported provider")
        return [
            SearchResult(
                title="API Demo Device",
                subtitle="demo",
                extra={"token": "demo"},
            )
        ]

    def connect_device(self, config: SearchResult) -> None:
        _ = config
        self.connected = True

    def disconnect_device(self) -> None:
        self.connected = False
        self.streaming = False

    def start_streaming(self) -> None:
        if not self.connected:
            raise RuntimeError("device is not connected")
        self.streaming = True

    def stop_streaming(self) -> None:
        self.streaming = False

    def on_shutdown(self) -> None:
        self.shutdown_called = True

    def emit_demo_frame(self, *, seq: int = 1) -> bool:
        return self.emit_frame(
            FrameEnvelope(
                device_id=self.device_id,
                stream_key="demo",
                timestamp_ns=123,
                data=np.ascontiguousarray([[1.0, 2.0, 3.0, 4.0]], dtype=np.float32),
                seq=seq,
            )
        )


class TimeoutSearchDriver(ApiDemoDriver):
    @property
    def device_id(self) -> str:
        return "timeout_demo.01"

    def search(self, provider: str) -> list[SearchResult]:
        raise TimeoutError("search timed out")


@pytest.fixture
def settings_path(tmp_path: Path) -> Path:
    path = tmp_path / "settings.json"
    settings = SettingsStore(path=path)
    settings.add(
        storage=SettingsGroup(
            root_dir=SettingsStr(default=""), export_root_dir=SettingsStr(default="")
        )
    )
    settings.storage.root_dir = str(tmp_path / "data")
    settings.save()
    return path


def test_app_lifespan_starts_and_shuts_down_engine(settings_path: Path) -> None:
    driver = ApiDemoDriver()
    app = create_app(settings_path=settings_path)

    with _patch_engine_discovery(lambda: driver):
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json()["ok"] is True

    assert driver.shutdown_called is True


def test_http_driver_endpoints_and_error_mapping(settings_path: Path) -> None:
    driver = ApiDemoDriver()
    app = create_app(settings_path=settings_path)

    with _patch_engine_discovery(lambda: driver):
        with TestClient(app) as client:
            drivers = client.get("/drivers")
            assert drivers.status_code == 200
            assert drivers.json()[0]["driver_id"] == driver.device_id

            search = client.post(
                f"/drivers/{driver.device_id}/search",
                json={"provider": "demo"},
            )
            assert search.status_code == 200
            assert search.json()[0]["title"] == "API Demo Device"

            bad_search = client.post(
                f"/drivers/{driver.device_id}/search",
                json={"provider": "bad"},
            )
            assert bad_search.status_code == 400
            assert bad_search.json()["error"]["type"] == "ValueError"

            connect = client.post(
                f"/drivers/{driver.device_id}/connect",
                json={
                    "title": "API Demo Device",
                    "subtitle": "demo",
                    "extra": {"token": "demo"},
                },
            )
            assert connect.status_code == 200

            start = client.post(f"/drivers/{driver.device_id}/start-streaming")
            assert start.status_code == 200

            descriptors = client.get("/streams/descriptors")
            assert descriptors.status_code == 200
            assert descriptors.json()[driver.descriptors()[0].stream_id]["stream_key"] == "demo"

            snapshot = client.get(f"/drivers/{driver.device_id}")
            assert snapshot.status_code == 200
            assert snapshot.json()["is_connected"] is True
            assert snapshot.json()["is_streaming"] is True

            stop = client.post(f"/drivers/{driver.device_id}/stop-streaming")
            assert stop.status_code == 200
            disconnect = client.post(f"/drivers/{driver.device_id}/disconnect")
            assert disconnect.status_code == 200


def test_http_acquisition_settings_and_timeout_mapping(settings_path: Path) -> None:
    app = create_app(settings_path=settings_path)

    with _patch_engine_discovery(TimeoutSearchDriver):
        with TestClient(app) as client:
            acquisition = client.get("/acquisition")
            assert acquisition.status_code == 200
            assert acquisition.json()["state"] == "idle"

            start_recording = client.post(
                "/acquisition/start-recording",
                json={"recording_label": None},
            )
            assert start_recording.status_code == 200
            assert start_recording.json() == {"ok": True}

            timeout_search = client.post(
                "/drivers/timeout_demo.01/search",
                json={"provider": "demo"},
            )
            assert timeout_search.status_code == 504
            assert timeout_search.json()["error"]["type"] == "TimeoutError"

            update = client.put(
                "/settings/storage.root_dir",
                json={"value": "C:/demo-data", "persist": False},
            )
            assert update.status_code == 200

            snapshot = client.get("/settings")
            assert snapshot.status_code == 200
            assert snapshot.json()["storage"]["root_dir"] == "C:/demo-data"

            delete = client.delete("/settings/storage.root_dir?persist=false")
            assert delete.status_code == 200


def test_sse_events_stream_emits_driver_connection_lost(settings_path: Path) -> None:
    driver = ApiDemoDriver()
    app = create_app(settings_path=settings_path)

    with _patch_engine_discovery(lambda: driver):
        with TestClient(app) as client:
            connect = client.post(
                f"/drivers/{driver.device_id}/connect",
                json={
                    "title": "API Demo Device",
                    "subtitle": "demo",
                    "extra": {"token": "demo"},
                },
            )
            assert connect.status_code == 200
            event_stream = client.app.state.engine.open_event_stream(maxsize=8)
            driver.emit_connection_lost({"code": "DEMO_LOST"})
            event_name, payload = _read_sse_event_from_generator(
                _iter_sse_messages(_ConnectedRequest(), event_stream)
            )

    assert event_name == "driver_connection_lost"
    assert payload["driver_id"] == driver.device_id
    assert payload["detail"] == {"code": "DEMO_LOST"}


def test_sse_events_stream_emits_resync_required_on_overflow(
    settings_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(settings_path=settings_path)

    with (
        _patch_engine_discovery(ApiDemoDriver),
        caplog.at_level(logging.WARNING),
        patch(
            "modlink_core.event_stream.EventStream.read",
            side_effect=EventStreamOverflowError("event stream overflowed"),
        ),
    ):
        with TestClient(app) as client:
            event_stream = client.app.state.engine.open_event_stream(maxsize=1)
            event_name, payload = _read_sse_event_from_generator(
                _iter_sse_messages(_ConnectedRequest(), event_stream)
            )

    assert event_name == "resync_required"
    assert payload == {"reason": "event_stream_overflow"}
    assert "overflowed" in caplog.text


def test_sse_events_stream_emits_keepalive_comment_when_idle(
    settings_path: Path,
) -> None:
    app = create_app(settings_path=settings_path)

    with _patch_engine_discovery(ApiDemoDriver):
        with TestClient(app) as client:
            event_stream = client.app.state.engine.open_event_stream(maxsize=1)
            chunk = _read_first_sse_chunk(
                _iter_sse_messages(
                    _ConnectedRequest(),
                    event_stream,
                    heartbeat_interval_seconds=0.0,
                )
            )

    assert chunk == ": keepalive\n\n"


def test_websocket_frames_stream_encodes_signal_frame(settings_path: Path) -> None:
    driver = ApiDemoDriver()
    app = create_app(settings_path=settings_path)
    stream_id = driver.descriptors()[0].stream_id

    with _patch_engine_discovery(lambda: driver):
        with TestClient(app) as client:
            with client.websocket_connect(f"/frames?stream_id={stream_id}") as websocket:
                emitted = driver.emit_demo_frame(seq=7)
                assert emitted is True
                payload = websocket.receive_json()

    assert payload["kind"] == "frame"
    assert payload["stream_id"] == stream_id
    assert payload["stream_key"] == "demo"
    assert payload["payload_type"] == "signal"
    assert payload["seq"] == 7
    assert payload["dtype"] == "float32"
    assert payload["shape"] == [1, 4]
    assert "extra" not in payload


def test_server_cli_help_exits_without_starting_server(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info, patch("modlink_server.app.uvicorn.run") as run:
        main(["--help"])

    assert exc_info.value.code == 0
    assert "Run the ModLink Studio HTTP server." in capsys.readouterr().out
    run.assert_not_called()


def _read_sse_event(lines) -> tuple[str, dict[str, object]]:
    event_name = ""
    payload = {}
    for line in lines:
        if not line:
            if event_name:
                return event_name, payload
            continue
        if line.startswith("event: "):
            event_name = line.removeprefix("event: ")
            continue
        if line.startswith("data: "):
            payload = json.loads(line.removeprefix("data: "))
    raise AssertionError("SSE event was not received")


def _read_sse_event_from_generator(generator) -> tuple[str, dict[str, object]]:
    return _read_sse_event(_collect_sse_lines(generator))


def _read_first_sse_chunk(generator) -> str:
    chunk = ""

    async def _read() -> None:
        nonlocal chunk
        async for item in generator:
            chunk = item
            break

    import asyncio

    asyncio.run(_read())
    return chunk


def _collect_sse_lines(generator) -> list[str]:
    chunks: list[str] = []

    async def _read() -> None:
        async for chunk in generator:
            chunks.extend(chunk.splitlines())
            break

    import asyncio

    asyncio.run(_read())
    return chunks


class _ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


def _patch_engine_discovery(*factories):
    return patch(
        "modlink_core.runtime.engine.discover_driver_factories",
        return_value=list(factories),
    )
