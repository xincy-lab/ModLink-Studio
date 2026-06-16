"""Public SDK data models shared by drivers, runtime services, and UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from .utils import make_stream_id, normalize_device_id, normalize_stream_key

type PayloadType = Literal["signal", "raster", "field", "video"]


@dataclass(slots=True)
class SearchResult:
    """One discovery candidate returned by ``Driver.search()``.

    Hosts use ``title`` and ``subtitle`` for presentation. ``extra`` is owned
    by the driver and is passed back to ``connect_device()`` unchanged.
    """

    title: str
    """Primary label shown to the user."""

    subtitle: str = ""
    """Optional secondary label shown to the user."""

    device_id: str | None = None
    """Optional canonical device identifier suggested by the driver."""

    extra: dict[str, Any] = field(default_factory=dict)
    """Driver-owned JSON-friendly payload for later connection."""

    def __post_init__(self) -> None:
        if self.device_id is not None:
            self.device_id = normalize_device_id(self.device_id)


@dataclass(slots=True)
class FrameEnvelope:
    """One emitted payload chunk from a driver.

    Drivers emit ``FrameEnvelope`` objects through their bound runtime
    context. The host forwards them to the stream bus, recording backends, and
    UI consumers.
    """

    device_id: str
    """Identifier of the device that produced this payload."""

    stream_key: str
    """Device-local stream key for this payload, such as ``eeg`` or ``video``."""

    stream_id: str = field(init=False)
    """Derived stable identifier of the stream that produced this payload."""

    timestamp_ns: int
    """Driver-supplied timestamp in nanoseconds."""

    data: np.ndarray
    """Payload array for this emitted chunk.

    The expected array shape depends on the matching ``StreamDescriptor``.
    """

    seq: int | None = None
    """Optional monotonically increasing sequence number."""

    def __post_init__(self) -> None:
        self.device_id = normalize_device_id(self.device_id)
        self.stream_key = normalize_stream_key(self.stream_key)
        self.stream_id = make_stream_id(self.device_id, self.stream_key)


def _validate_channel_names(names: tuple[str, ...]) -> None:
    """Reject channel names that are not CSV-safe at construction time."""
    for name in names:
        if name == "":
            raise ValueError(f"channel_name {name!r} is not CSV-safe: contains empty string")
        if name != name.lstrip():
            raise ValueError(f"channel_name {name!r} is not CSV-safe: contains leading whitespace")
        if name != name.rstrip():
            raise ValueError(f"channel_name {name!r} is not CSV-safe: contains trailing whitespace")
        if "," in name:
            raise ValueError(f"channel_name {name!r} is not CSV-safe: contains ','")
        if "\n" in name:
            raise ValueError(f"channel_name {name!r} is not CSV-safe: contains '\\n'")
        if "\r" in name:
            raise ValueError(f"channel_name {name!r} is not CSV-safe: contains '\\r'")
        if "\0" in name:
            raise ValueError(f"channel_name {name!r} is not CSV-safe: contains '\\0'")


@dataclass(slots=True)
class StreamDescriptor:
    """Static metadata describing one stream exposed by a driver.

    Hosts may read descriptors before a device is connected. The returned
    values should remain stable for the lifetime of the driver instance.
    """

    device_id: str
    """Stable device identifier in ``name.XX`` form."""

    stream_key: str
    """Device-local stream key, such as ``eeg``, ``accel``, or ``audio``."""

    stream_id: str = field(init=False)
    """Derived stable identifier for this stream."""

    payload_type: PayloadType
    """Payload type used to interpret ``FrameEnvelope.data``."""

    nominal_sample_rate_hz: float
    """Nominal sample rate in Hz."""

    chunk_size: int
    """Expected number of samples or frames per emitted chunk."""

    channel_names: tuple[str, ...] = ()
    """Optional channel labels, usually matching axis 0 for signal payloads."""

    display_name: str | None = None
    """Optional human-readable stream label."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata, including payload-specific fields such as ``unit``."""

    def __post_init__(self) -> None:
        self.device_id = normalize_device_id(self.device_id)
        self.stream_key = normalize_stream_key(self.stream_key)
        self.stream_id = make_stream_id(self.device_id, self.stream_key)
        self.metadata = dict(self.metadata)
        _validate_channel_names(self.channel_names)
