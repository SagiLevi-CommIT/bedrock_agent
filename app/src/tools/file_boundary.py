"""Find rt_flow CSV files whose real sampling_time overlaps a UTC window."""

from __future__ import annotations

from datetime import datetime, timedelta

from ..lib.cs_downloader.boundary import find_boundaries
from ..lib.cs_downloader.config import default_flows
from ..settings import get_client
from . import app_events as ae
from . import tool


@tool(
    name="find_rt_flow_files_in_window",
    description=(
        "List rearrangement rt_flow files for a patient, then bisect+probe to "
        "find files whose CSV sampling_time overlaps [start_utc, end_utc]. "
        "Returns summary + overlapping file keys with probed ranges."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "patient_id": {"type": "integer"},
            "start_utc": {"type": "string", "description": "ISO-8601 UTC inclusive"},
            "end_utc": {"type": "string", "description": "ISO-8601 UTC inclusive"},
            "max_files": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
        },
        "required": ["patient_id", "start_utc", "end_utc"],
    },
)
def find_rt_flow_files_in_window(
    patient_id: int,
    start_utc: str,
    end_utc: str,
    max_files: int = 100,
) -> str:
    s_dt = ae._parse_iso(start_utc)
    e_dt = ae._parse_iso(end_utc)
    if s_dt is None or e_dt is None or e_dt <= s_dt:
        return "ERROR: invalid start_utc/end_utc ISO timestamps (expect UTC, end > start)."

    cfg = default_flows()["rt_flow"]
    safety_min = cfg.estimated_chunk_duration_min + cfg.typical_upload_lag_min + 5
    epoch_start_ms = int((s_dt - timedelta(minutes=safety_min)).timestamp() * 1000)
    epoch_end_ms = int((e_dt + timedelta(minutes=safety_min)).timestamp() * 1000)

    files = ae._list_files_internal(
        int(patient_id), "rt_flow", "rearrangement", epoch_start_ms, epoch_end_ms
    )
    if not files:
        return (
            f"No rt_flow rearrangement files for patient_id={patient_id} near window "
            f"{start_utc}..{end_utc}."
        )

    s3 = get_client("s3")
    left, right, cache = find_boundaries(
        s3, ae.APP_EVENTS_BUCKET, files, s_dt, e_dt, cfg, probe_bytes=8192
    )
    if left is None or right is None:
        return (
            f"Could not bracket window in probed rt_flow files "
            f"(listed={len(files)}, left={left}, right={right}). "
            "Try widening the window slightly or use list_patient_files + probe_file_time_range."
        )

    lo, hi = min(left, right), max(left, right)
    slice_files = files[lo : hi + 1][:max_files]
    overlapping: list[tuple[str, datetime, datetime]] = []
    for f in slice_files:
        rng = cache.get(f.key)
        if rng is None:
            continue
        mn, mx = rng
        if mx >= s_dt and mn <= e_dt:
            overlapping.append((f.key, mn, mx))

    lines = [
        f"files_listed={len(files)} boundaries=[{lo},{hi}] files_probed={len(cache)} "
        f"files_overlapping={len(overlapping)}",
        "",
    ]
    if not overlapping:
        lines.append("No files overlap the requested time range after probing boundaries.")
        return "\n".join(lines)

    next_hint = ""
    if hi + 1 < len(files):
        next_hint = f"next_file_start_utc={files[hi + 1].filename_epoch_dt.isoformat()}"

    for key, mn, mx in overlapping[:50]:
        lines.append(f"{key}\n  sampling_time: {mn.isoformat()} → {mx.isoformat()}")
    if len(overlapping) > 50:
        lines.append(f"... and {len(overlapping) - 50} more")
    if next_hint:
        lines.append("")
        lines.append(next_hint)
    return "\n".join(lines)
