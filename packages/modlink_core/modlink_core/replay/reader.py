from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from modlink_sdk import FrameEnvelope, PayloadType, StreamDescriptor

from ..models import ReplayMarker, ReplaySegment
from ..storage import (
    load_recording_frame_data,
    read_recording,
    read_recording_frames,
    read_recording_markers,
    read_recording_segments,
    read_recording_stream,
)


@dataclass(frozen=True, slots=True)
class RecordedFrameRef:
    stream_id: str
    frame_index: int
    timestamp_ns: int
    seq: int | None
    file_name: str
    relative_timestamp_ns: int


class RecordingReader:
    def __init__(self, recording_path: str | Path) -> None:
        self._recording_path = Path(recording_path)
        if not (self._recording_path / "recording.json").is_file():
            raise FileNotFoundError(self._recording_path / "recording.json")

        self._recording_id = self._recording_path.name
        self._root_dir = self._recording_path.parent.parent
        self._manifest = read_recording(self._root_dir, self._recording_id)
        stream_ids = self._manifest.get("stream_ids", [])
        if not isinstance(stream_ids, list):
            raise ValueError(f"recording '{self._recording_id}' has invalid stream_ids payload")

        descriptors: dict[str, StreamDescriptor] = {}
        frames_by_stream: dict[str, tuple[RecordedFrameRef, ...]] = {}
        timeline_seed: list[RecordedFrameRef] = []
        marker_payload = read_recording_markers(self._root_dir, self._recording_id)
        segment_payload = read_recording_segments(self._root_dir, self._recording_id)

        raw_frame_refs: list[tuple[str, int, int, int | None, str]] = []
        for stream_id in stream_ids:
            if not isinstance(stream_id, str):
                raise ValueError(
                    f"recording '{self._recording_id}' contains a non-string stream_id"
                )
            stream_payload = read_recording_stream(self._root_dir, self._recording_id, stream_id)
            descriptors[stream_id] = _descriptor_from_payload(stream_payload)
            stream_frame_refs = tuple(
                _parse_frame_rows(
                    read_recording_frames(self._root_dir, self._recording_id, stream_id), stream_id
                )
            )
            frames_by_stream[stream_id] = stream_frame_refs
            for ref in stream_frame_refs:
                raw_frame_refs.append(
                    (ref.stream_id, ref.frame_index, ref.timestamp_ns, ref.seq, ref.file_name)
                )

        raw_frame_refs.sort(key=lambda item: (item[2], item[0], item[1]))
        start_ns = raw_frame_refs[0][2] if raw_frame_refs else 0
        for stream_id, frame_index, timestamp_ns, seq, file_name in raw_frame_refs:
            timeline_seed.append(
                RecordedFrameRef(
                    stream_id=stream_id,
                    frame_index=frame_index,
                    timestamp_ns=timestamp_ns,
                    seq=seq,
                    file_name=file_name,
                    relative_timestamp_ns=max(0, timestamp_ns - start_ns),
                )
            )

        normalized_frames_by_stream: dict[str, tuple[RecordedFrameRef, ...]] = {}
        relative_by_key = {
            (item.stream_id, item.frame_index): item.relative_timestamp_ns for item in timeline_seed
        }
        for stream_id, refs in frames_by_stream.items():
            normalized_frames_by_stream[stream_id] = tuple(
                RecordedFrameRef(
                    stream_id=ref.stream_id,
                    frame_index=ref.frame_index,
                    timestamp_ns=ref.timestamp_ns,
                    seq=ref.seq,
                    file_name=ref.file_name,
                    relative_timestamp_ns=relative_by_key[(ref.stream_id, ref.frame_index)],
                )
                for ref in refs
            )

        self._descriptors = descriptors
        self._frames_by_stream = normalized_frames_by_stream
        self._timeline = tuple(timeline_seed)
        self._start_ns = start_ns
        self._end_ns = self._timeline[-1].timestamp_ns if self._timeline else 0
        self._duration_ns = max(0, self._end_ns - self._start_ns)
        self._markers = tuple(_parse_markers(marker_payload, self._start_ns))
        self._segments = tuple(_parse_segments(segment_payload, self._start_ns))
        self._value_range_cache: dict[str, tuple[float, float]] = {}

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    @property
    def recording_id(self) -> str:
        return self._recording_id

    @property
    def recording_path(self) -> Path:
        return self._recording_path

    @property
    def recording_label(self) -> str | None:
        label = self._manifest.get("recording_label")
        return label if isinstance(label, str) or label is None else str(label)

    @property
    def session_name(self) -> str | None:
        value = self._manifest.get("session_name")
        return value if isinstance(value, str) else None

    @property
    def experiment_name(self) -> str | None:
        value = self._manifest.get("experiment_name")
        return value if isinstance(value, str) else None

    @property
    def started_at_ns(self) -> int | None:
        return self._manifest.get("started_at_ns")

    @property
    def stopped_at_ns(self) -> int | None:
        return self._manifest.get("stopped_at_ns")

    @property
    def status(self) -> str | None:
        return self._manifest.get("status")

    @property
    def frame_counts_by_stream(self) -> dict[str, int]:
        cached = self._manifest.get("frame_counts_by_stream")
        if isinstance(cached, dict):
            return dict(cached)
        return {sid: len(refs) for sid, refs in self._frames_by_stream.items()}

    @property
    def manifest(self) -> dict[str, Any]:
        return dict(self._manifest)

    @property
    def start_ns(self) -> int:
        return self._start_ns

    @property
    def end_ns(self) -> int:
        return self._end_ns

    @property
    def duration_ns(self) -> int:
        return self._duration_ns

    def descriptors(self) -> dict[str, StreamDescriptor]:
        return dict(self._descriptors)

    def descriptor(self, stream_id: str) -> StreamDescriptor | None:
        return self._descriptors.get(stream_id)

    def stream_ids(self) -> tuple[str, ...]:
        return tuple(self._descriptors.keys())

    def markers(self) -> tuple[ReplayMarker, ...]:
        return self._markers

    def segments(self) -> tuple[ReplaySegment, ...]:
        return self._segments

    def frames(self) -> tuple[RecordedFrameRef, ...]:
        return self._timeline

    def frames_for_stream(self, stream_id: str) -> tuple[RecordedFrameRef, ...]:
        return self._frames_by_stream.get(stream_id, ())

    def frames_in_range(
        self, stream_id: str, start_ns: int, end_ns: int
    ) -> tuple[RecordedFrameRef, ...]:
        refs = self._frames_by_stream.get(stream_id)
        if not refs:
            return ()
        return tuple(r for r in refs if start_ns <= r.relative_timestamp_ns < end_ns)

    def markers_in_range(self, start_ns: int, end_ns: int) -> tuple[ReplayMarker, ...]:
        return tuple(m for m in self._markers if start_ns <= m.timestamp_ns < end_ns)

    def overlapping_segments(self, start_ns: int, end_ns: int) -> tuple[ReplaySegment, ...]:
        return tuple(s for s in self._segments if s.start_ns < end_ns and s.end_ns > start_ns)

    def stream_value_range(self, stream_id: str) -> tuple[float, float] | None:
        if stream_id in self._value_range_cache:
            return self._value_range_cache[stream_id]
        refs = self._frames_by_stream.get(stream_id)
        if not refs:
            return None
        global_min: float | None = None
        global_max: float | None = None
        for ref in refs:
            envelope = self.load_frame(ref)
            frame_min = float(envelope.data.min())
            frame_max = float(envelope.data.max())
            if global_min is None or frame_min < global_min:
                global_min = frame_min
            if global_max is None or frame_max > global_max:
                global_max = frame_max
        if global_min is None or global_max is None:
            return None
        result = (global_min, global_max)
        self._value_range_cache[stream_id] = result
        return result

    def load_frame(self, ref: RecordedFrameRef) -> FrameEnvelope:
        descriptor = self._descriptors[ref.stream_id]
        return FrameEnvelope(
            device_id=descriptor.device_id,
            stream_key=descriptor.stream_key,
            timestamp_ns=ref.timestamp_ns,
            data=load_recording_frame_data(
                self._root_dir,
                self._recording_id,
                ref.stream_id,
                ref.file_name,
            ),
            seq=ref.seq,
        )


def _descriptor_from_payload(payload: dict[str, Any]) -> StreamDescriptor:
    descriptor_payload = payload.get("descriptor")
    if not isinstance(descriptor_payload, dict):
        raise ValueError("stream manifest is missing descriptor payload")

    payload_type = descriptor_payload.get("payload_type")
    if not isinstance(payload_type, str):
        raise ValueError("stream descriptor is missing payload_type")

    channel_names = descriptor_payload.get("channel_names") or ()
    if not isinstance(channel_names, list | tuple):
        raise ValueError("stream descriptor channel_names must be a sequence")

    return StreamDescriptor(
        device_id=str(descriptor_payload.get("device_id") or ""),
        stream_key=str(descriptor_payload.get("stream_key") or ""),
        payload_type=cast(PayloadType, payload_type),
        nominal_sample_rate_hz=float(descriptor_payload.get("nominal_sample_rate_hz") or 0.0),
        chunk_size=int(descriptor_payload.get("chunk_size") or 0),
        channel_names=tuple(str(name) for name in channel_names),
        display_name=_optional_text(descriptor_payload.get("display_name")),
        metadata=_dict_payload(descriptor_payload.get("metadata")),
    )


def _parse_frame_rows(rows: list[dict[str, str]], stream_id: str) -> list[RecordedFrameRef]:
    refs: list[RecordedFrameRef] = []
    for row in rows:
        frame_index = int(row["frame_index"])
        timestamp_ns = int(row["timestamp_ns"])
        seq_text = row.get("seq", "")
        refs.append(
            RecordedFrameRef(
                stream_id=stream_id,
                frame_index=frame_index,
                timestamp_ns=timestamp_ns,
                seq=None if seq_text == "" else int(seq_text),
                file_name=str(row["file_name"]),
                relative_timestamp_ns=0,
            )
        )
    return refs


def _parse_markers(rows: list[dict[str, str]], start_ns: int) -> list[ReplayMarker]:
    markers: list[ReplayMarker] = []
    for row in rows:
        markers.append(
            ReplayMarker(
                timestamp_ns=max(0, int(row["timestamp_ns"]) - start_ns),
                label=_optional_text(row.get("label")),
            )
        )
    return markers


def _parse_segments(rows: list[dict[str, str]], start_ns: int) -> list[ReplaySegment]:
    segments: list[ReplaySegment] = []
    for row in rows:
        segments.append(
            ReplaySegment(
                start_ns=max(0, int(row["start_ns"]) - start_ns),
                end_ns=max(0, int(row["end_ns"]) - start_ns),
                label=_optional_text(row.get("label")),
            )
        )
    return segments


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dict_payload(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}
