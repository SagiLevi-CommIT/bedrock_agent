"""S3 CSV time-range probing (HEAD + ranged GETs)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from ..lib.cs_downloader import probe_time_range
from ..settings import get_client
from . import tool

_DEFAULT_BUCKET = "735555370207-app-events"


def _format_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@tool(
    name="probe_file_time_range",
    description=(
        "Read only the first and last few KB of a CSV in S3 to determine "
        "min/max sampling_time. Cost: 1 HEAD + 2 ranged GETs. Default bucket "
        "is the CardiacSense app-events bucket."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "bucket": {"type": "string", "default": _DEFAULT_BUCKET},
            "probe_bytes": {"type": "integer", "default": 8192, "minimum": 1024, "maximum": 65536},
        },
        "required": ["key"],
    },
)
def probe_file_time_range(
    key: str,
    bucket: str = _DEFAULT_BUCKET,
    probe_bytes: int = 8192,
) -> str:
    s3 = get_client("s3")
    head = s3.head_object(Bucket=bucket, Key=key)
    file_size = head["ContentLength"]
    last_modified = head["LastModified"]
    try:
        ts_min, ts_max = probe_time_range(s3, bucket, key, probe_bytes=probe_bytes)
    except Exception as e:  # noqa: BLE001
        return f"ERROR: probe failed for {key!r}: {type(e).__name__}: {e}"
    duration_min = (ts_max - ts_min).total_seconds() / 60.0
    return (
        f"Probed {key} ({file_size:,} bytes)\n"
        f"Signal range: {ts_min.isoformat()} → {ts_max.isoformat()} "
        f"(duration {duration_min:.2f} min)\n"
        f"S3 LastModified: {last_modified.isoformat()}\n"
        f"Probe cost: 1 HEAD + 2 ranged GETs (~{2 * probe_bytes // 1024} KB)"
    )


@tool(
    name="probe_files_batch",
    description=(
        "Probe up to 50 S3 CSV keys in parallel (max 10 workers) for "
        "sampling_time min/max per file. Failed keys are omitted from the map."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "keys": {"type": "array", "items": {"type": "string"}},
            "bucket": {"type": "string", "default": _DEFAULT_BUCKET},
            "max_workers": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
        },
        "required": ["keys"],
    },
)
def probe_files_batch(
    keys: list[str],
    bucket: str = _DEFAULT_BUCKET,
    max_workers: int = 5,
) -> str:
    if len(keys) > 50:
        return f"ERROR: at most 50 keys allowed, got {len(keys)}"
    mw = max(1, min(10, int(max_workers)))
    s3 = get_client("s3")
    results: dict[str, tuple[datetime, datetime]] = {}

    def _one(k: str) -> tuple[str, tuple[datetime, datetime] | None]:
        try:
            return k, probe_time_range(s3, bucket, k)
        except Exception:
            return k, None

    with ThreadPoolExecutor(max_workers=mw) as pool:
        futs = [pool.submit(_one, k) for k in keys]
        for fut in as_completed(futs):
            k, rng = fut.result()
            if rng is not None:
                results[k] = rng

    lines = [f"Probed {len(results)}/{len(keys)} files OK (bucket={bucket}).", ""]
    for k, (mn, mx) in list(results.items())[:40]:
        lines.append(f"{k}\n  min={_format_ts(mn)} max={_format_ts(mx)}")
    if len(results) > 40:
        lines.append(f"... and {len(results) - 40} more")
    return "\n".join(lines)
