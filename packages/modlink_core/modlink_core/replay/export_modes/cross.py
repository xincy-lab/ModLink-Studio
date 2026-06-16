from __future__ import annotations

import csv
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from ...storage._internal.ids import safe_path_component
from ..export_request import ExportRequest
from ..package_writer import ExportPackageWriter
from ..store import RecordingStore


def export_cross_recording_stream(
    request: ExportRequest,
    store: RecordingStore,
    output_root: Path,
    progress_fn: Callable[[str], None] | None = None,
) -> Path:
    """Export one stream across multiple recordings.

    If request.concat_streams=True: produce a single CSV with recording_id column.
    If request.concat_streams=False: produce per-recording subdirectories.
    Returns the final bundle path.
    """
    if len(request.streams) != 1:
        raise ValueError(
            f"CROSS_STREAM mode requires exactly 1 StreamSelection, got {len(request.streams)}"
        )

    sel = request.streams[0]
    stream_id = sel.stream_id
    # stream_key is the stream_id used as the directory/file key
    stream_key = stream_id
    stream_key_safe = safe_path_component(stream_key)

    bundle_name = f"cross_{stream_key_safe}_{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%S')}"

    skipped: list[str] = []
    included: list[str] = []

    with ExportPackageWriter(output_root / bundle_name) as pkg:
        if request.concat_streams and sel.format_id == "signal_csv":
            _write_concat_csv(
                pkg,
                request,
                store,
                stream_id,
                stream_key,
                stream_key_safe,
                included,
                skipped,
                progress_fn,
            )
        else:
            _write_per_recording(
                pkg,
                request,
                store,
                stream_id,
                stream_key,
                stream_key_safe,
                included,
                skipped,
                progress_fn,
            )

        _write_manifest(pkg, bundle_name, stream_key, included, skipped, request.concat_streams)
        _write_readme(pkg, bundle_name, stream_key, included, request.concat_streams)

    return pkg.final_path


def _write_concat_csv(
    pkg: ExportPackageWriter,
    request: ExportRequest,
    store: RecordingStore,
    stream_id: str,
    stream_key: str,
    stream_key_safe: str,
    included: list[str],
    skipped: list[str],
    progress_fn: Callable[[str], None] | None,
) -> None:
    streams_dir = pkg.root / "streams"
    streams_dir.mkdir()
    out_path = streams_dir / f"{stream_key_safe}_concat.csv"

    # Collect channel headers from the first recording that has the stream
    channel_headers: list[str] | None = None
    sample_rate_hz: float | None = None

    # First pass: determine headers
    for rec_id in request.recording_ids:
        reader = store.open(rec_id)
        descriptor = reader.descriptor(stream_id)
        if descriptor is None:
            continue
        if descriptor.channel_names:
            channel_headers = list(descriptor.channel_names)
        else:
            frame_refs = reader.frames_for_stream(stream_id)
            if frame_refs:
                first_data = reader.load_frame(frame_refs[0]).data
                n_ch = first_data.shape[0]
            else:
                n_ch = 0
            channel_headers = [f"ch{i + 1}" for i in range(n_ch)]
        sample_rate_hz = descriptor.nominal_sample_rate_hz
        break

    if channel_headers is None:
        # No recording has this stream — all skipped
        for rec_id in request.recording_ids:
            skipped.append(rec_id)
        # Write empty CSV with just the header
        with out_path.open("w", encoding="utf-8", newline="") as fh:
            csv.writer(fh).writerow(["recording_id", "timestamp_ns"])
        return

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["recording_id", "timestamp_ns", *channel_headers])

        for rec_id in request.recording_ids:
            if progress_fn:
                progress_fn(f"concat {rec_id}")
            reader = store.open(rec_id)
            descriptor = reader.descriptor(stream_id)
            if descriptor is None:
                skipped.append(rec_id)
                continue

            included.append(rec_id)
            frame_refs = reader.frames_for_stream(stream_id)
            rate = descriptor.nominal_sample_rate_hz
            if rate <= 0:
                rate = sample_rate_hz or 1.0
            ns_per_sample = 1_000_000_000 / rate

            for ref in frame_refs:
                envelope = reader.load_frame(ref)
                data = envelope.data  # shape (C, T)
                chunk_ts = envelope.timestamp_ns
                num_samples = data.shape[1]
                for i in range(num_samples):
                    sample_ts = int(chunk_ts + i * ns_per_sample)
                    writer.writerow([rec_id, sample_ts, *data[:, i].tolist()])


def _write_per_recording(
    pkg: ExportPackageWriter,
    request: ExportRequest,
    store: RecordingStore,
    stream_id: str,
    stream_key: str,
    stream_key_safe: str,
    included: list[str],
    skipped: list[str],
    progress_fn: Callable[[str], None] | None,
) -> None:
    from ..format.signal_csv import write_signal_csv

    recordings_dir = pkg.root / "recordings"
    recordings_dir.mkdir()

    for rec_id in request.recording_ids:
        if progress_fn:
            progress_fn(f"export {rec_id}")
        reader = store.open(rec_id)
        descriptor = reader.descriptor(stream_id)
        if descriptor is None:
            skipped.append(rec_id)
            continue

        included.append(rec_id)
        rec_streams_dir = recordings_dir / rec_id / "streams"
        rec_streams_dir.mkdir(parents=True)

        frame_refs = reader.frames_for_stream(stream_id)
        out_path = rec_streams_dir / f"{stream_key_safe}.csv"
        write_signal_csv(reader, stream_id, frame_refs, out_path)


def _write_manifest(
    pkg: ExportPackageWriter,
    bundle_name: str,
    stream_key: str,
    included: list[str],
    skipped: list[str],
    concat: bool,
) -> None:
    manifest = {
        "bundle_name": bundle_name,
        "mode": "cross_stream",
        "stream_key": stream_key,
        "recording_ids": included,
        "skipped_recordings": skipped,
        "concat": concat,
        "created_at": datetime.now(tz=UTC).isoformat(),
    }
    (pkg.root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _write_readme(
    pkg: ExportPackageWriter,
    bundle_name: str,
    stream_key: str,
    included: list[str],
    concat: bool,
) -> None:
    rec_list = "\n".join(f"- `{r}`" for r in included) if included else "*(none)*"
    structure = f"{bundle_name}/\n├── manifest.json\n├── README.md\n" + (
        f"└── streams/\n    └── {stream_key}_concat.csv"
        if concat
        else f"└── recordings/\n    ├── <rec_id>/streams/{stream_key}.csv\n    └── ..."
    )
    readme = f"""\
# Export Bundle: {bundle_name}

## Contents

- **Mode**: cross_stream
- **Stream**: `{stream_key}`
- **Recordings**: {len(included)}
- **Concat**: {concat}

## Directory Structure

```
{structure}
```

## Recordings Exported

{rec_list}

---
*Generated by ModLink Studio export system*
"""
    (pkg.root / "README.md").write_text(readme, encoding="utf-8")
