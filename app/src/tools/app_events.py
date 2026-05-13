"""S3-key-aware tools for the CardiacSense app-events bucket.

Wraps the vendored cs_downloader library so the agent can:
  - parse a key into (stage, flow, patient_id, epoch_ms, role)
  - list a patient's files in a flow with prefix narrowing + StartAfter
  - probe the actual signal start/end inside a CSV (vs S3 LastModified)
  - find the most recent upload across all flows
  - summarize per-day usage cheaply (no probing)
  - merge a time-windowed file set into a single CSV uploaded to the
    agent's results bucket and return a presigned URL

All tools are read-only on the data buckets. Only the merge tool writes — and
only to the agent's own results bucket (configured via APP settings).
"""
from __future__ import annotations

import io
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from ..lib.cs_downloader import (
    FileInfo,
    default_flows,
    download_and_merge_inmemory,
    extract_filename_epoch,
    list_patient_files as _cs_list_patient_files,
)
from ..settings import get_client, get_settings
from . import tool

APP_EVENTS_BUCKET = "735555370207-app-events"
KNOWN_FLOWS: tuple[str, ...] = (
    "rt_flow",
    "sleep_flow",
    "ar_flow",
    "af_ppg_flow",
    "tachycardia_flow",
    "plate_flow",
    "arrythmia_flow",
    "algos_flow",
)

# Regex registry — must agree with knowledge/naming_conventions.md and
# skills/naming_conventions.yaml.
_KEY_PATTERNS: list[tuple[re.Pattern[str], dict[str, str]]] = [
    (
        re.compile(
            r"^rearrangement/(?P<flow>[a-z_]+_flow)/(?P=flow)_"
            r"(?P<patient_id>\d+)_(?P<epoch_ms>\d{13})\.csv$"
        ),
        {"stage": "rearrangement", "role": "data"},
    ),
    (
        re.compile(
            r"^rearrangement/(?P<flow>[a-z_]+_flow)/(?P=flow)_"
            r"(?P<patient_id>\d+)_(?P<epoch_ms>\d{13})_metadata\.txt$"
        ),
        {"stage": "rearrangement", "role": "metadata"},
    ),
    (
        re.compile(
            r"^rearrangement/(?P<flow>[a-z_]+_flow)/(?P=flow)_"
            r"(?P<patient_id>\d+)_(?P<epoch_ms>\d{13})_session\.tmp$"
        ),
        {"stage": "rearrangement", "role": "session"},
    ),
    (
        re.compile(
            r"^post-computation-layer/(?P<flow>[a-z_]+_flow)/(?P=flow)_"
            r"(?P<patient_id>\d+)_(?P<epoch_ms>\d{13})\.csv$"
        ),
        {"stage": "post_computation", "role": "data"},
    ),
    (
        re.compile(
            r"^post-computation-layer/(?P<flow>[a-z_]+_flow)/(?P=flow)_"
            r"(?P<patient_id>\d+)_(?P<epoch_ms>\d{13})\.json$"
        ),
        {"stage": "post_computation", "role": "summary_json"},
    ),
    (
        re.compile(
            r"^post-computation-layer/(?P<flow>[a-z_]+_flow)/(?P=flow)_"
            r"(?P<patient_id>\d+)_(?P<epoch_ms>\d{13})-avg-values\.csv$"
        ),
        {"stage": "post_computation", "role": "avg_values"},
    ),
    (
        re.compile(r"^processed/cs_events_(?P<patient_id>\d+)_(?P<epoch_sec>\d{10})\.csv$"),
        {"stage": "processed", "role": "events", "flow": ""},
    ),
    (
        re.compile(
            r"^incoming/(?P<flow>[a-z_]+_flow)_(?P<patient_id>\d+)_(?P<epoch_ms>\d{13})\.dat\.zip$"
        ),
        {"stage": "incoming", "role": "binary"},
    ),
    (
        re.compile(
            r"^rt-sessions/cs_realtime_(?P<patient_id>\d+)_(?P<local_ts>\d{14})\.json$"
        ),
        {"stage": "rt_sessions", "role": "session_json", "flow": ""},
    ),
    (
        re.compile(
            r"^doctor-realtime-session/realtime-doctor[Ii]d-(?P<doctor_id>\d+)-pId-"
            r"(?P<patient_id>\d+)-(?P<epoch_ms>\d{13})\.json$"
        ),
        {"stage": "doctor_session", "role": "session_json", "flow": ""},
    ),
    (
        re.compile(
            r"^doctor-realtime-session/realtime-docId-(?P<doctor_id>\d+)-pId-"
            r"(?P<patient_id>\d+)-(?P<epoch_ms>\d{13})\.json$"
        ),
        {"stage": "doctor_session", "role": "session_json", "flow": ""},
    ),
    (
        re.compile(
            r"^doctor-realtime-session/(?P<doctor_id>\d+)-(?P<patient_id>\d+)-realtime\.json$"
        ),
        {"stage": "doctor_session", "role": "session_json_legacy", "flow": ""},
    ),
]


def _parse_key(key: str) -> dict[str, str | int] | None:
    for pattern, extra in _KEY_PATTERNS:
        m = pattern.match(key)
        if m:
            d = m.groupdict()
            d.update(extra)
            for int_field in ("patient_id", "epoch_ms", "epoch_sec", "doctor_id"):
                if d.get(int_field) is not None:
                    d[int_field] = int(d[int_field])
            return d
    return None


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    s = ts.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _format_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ────────────────────────────────────────────────────────────────────────
# 1. parse_app_events_key
# ────────────────────────────────────────────────────────────────────────
@tool(
    name="parse_app_events_key",
    description=(
        "Parse an S3 key from the 735555370207-app-events bucket into a "
        "structured dict: {stage, flow, patient_id, epoch_ms or epoch_sec, "
        "role}. Recognizes rearrangement, post-computation, processed, "
        "incoming, rt-sessions, and doctor-realtime-session patterns. "
        "Returns ERROR if the key matches no known pattern — never guess."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "S3 object key (no s3:// prefix)"},
        },
        "required": ["key"],
    },
)
def parse_app_events_key(key: str) -> str:
    parsed = _parse_key(key)
    if parsed is None:
        return f"ERROR: key {key!r} matches no known pattern. See knowledge/naming_conventions.md."
    if "epoch_ms" in parsed:
        dt = datetime.fromtimestamp(int(parsed["epoch_ms"]) / 1000, tz=timezone.utc)
        parsed["recorded_at"] = _format_ts(dt)
    elif "epoch_sec" in parsed:
        dt = datetime.fromtimestamp(int(parsed["epoch_sec"]), tz=timezone.utc)
        parsed["recorded_at"] = _format_ts(dt)
    lines = [f"Parsed key {key!r}:"]
    for k, v in parsed.items():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────────
# 2. list_patient_files
# ────────────────────────────────────────────────────────────────────────
def _list_files_internal(
    patient_id: int,
    flow: str,
    stage: str = "rearrangement",
    epoch_start_ms: int | None = None,
    epoch_end_ms: int | None = None,
) -> list[FileInfo]:
    """Internal — returns FileInfo list for either rearrangement (via cs_downloader)
    or post-computation (via direct boto3 LIST). Skips folder-marker keys."""
    s3 = get_client("s3")
    if stage == "rearrangement":
        return _cs_list_patient_files(
            s3,
            APP_EVENTS_BUCKET,
            flow,
            patient_id,
            epoch_start_ms=epoch_start_ms,
            epoch_end_ms=epoch_end_ms,
        )
    # post-computation: cs_downloader doesn't cover this stage. LIST manually.
    if stage != "post_computation":
        raise ValueError(f"unknown stage: {stage!r}")
    prefix = f"post-computation-layer/{flow}/{flow}_{patient_id}_"
    kwargs: dict = {"Bucket": APP_EVENTS_BUCKET, "Prefix": prefix, "MaxKeys": 1000}
    if epoch_start_ms is not None:
        kwargs["StartAfter"] = f"{prefix}{epoch_start_ms}"
    files: list[FileInfo] = []
    token: str | None = None
    while True:
        if token:
            kwargs["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kwargs)
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue  # folder marker
            if not key.endswith(".csv"):
                continue
            if "-avg-values" in key:
                continue  # avg-values is the per-session aggregate; skip for "data" listing
            try:
                epoch_ms = extract_filename_epoch(key)
            except ValueError:
                continue
            if epoch_end_ms is not None and epoch_ms > epoch_end_ms:
                files.sort(key=lambda f: f.filename_epoch_ms)
                return files
            files.append(
                FileInfo(
                    key=key,
                    size=obj["Size"],
                    filename_epoch_ms=epoch_ms,
                    filename_epoch_dt=datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc),
                )
            )
        if resp.get("IsTruncated"):
            token = resp["NextContinuationToken"]
        else:
            break
    files.sort(key=lambda f: f.filename_epoch_ms)
    return files


@tool(
    name="list_patient_files",
    description=(
        "List CSV files for a single patient in a single flow + stage, sorted "
        "chronologically by filename epoch_ms. Uses tight prefix narrowing + "
        "S3 StartAfter for cheap retrieval. stage is 'rearrangement' (default, "
        "all 8 flows) or 'post_computation' (only rt_flow / arrythmia_flow / "
        "plate_flow). Optional time_window narrows by recording-start epoch_ms "
        "encoded in filename. Returns up to `limit` rows."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "patient_id": {"type": "integer", "description": "Bare integer patient_id"},
            "flow": {"type": "string", "enum": list(KNOWN_FLOWS)},
            "stage": {
                "type": "string",
                "enum": ["rearrangement", "post_computation"],
                "default": "rearrangement",
            },
            "time_window": {
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "ISO-8601 UTC, inclusive"},
                    "end": {"type": "string", "description": "ISO-8601 UTC, inclusive"},
                },
            },
            "limit": {"type": "integer", "default": 200, "minimum": 1, "maximum": 2000},
        },
        "required": ["patient_id", "flow"],
    },
)
def list_patient_files(
    patient_id: int,
    flow: str,
    stage: str = "rearrangement",
    time_window: dict | None = None,
    limit: int = 200,
) -> str:
    if flow not in KNOWN_FLOWS:
        return f"ERROR: unknown flow {flow!r}. Known: {KNOWN_FLOWS}"
    if stage == "post_computation" and flow not in ("rt_flow", "arrythmia_flow", "plate_flow"):
        return (
            f"ERROR: post_computation has no data for flow {flow!r}. "
            "Only rt_flow / arrythmia_flow / plate_flow have post-computation files."
        )
    epoch_start_ms = None
    epoch_end_ms = None
    if time_window:
        s = _parse_iso(time_window.get("start"))
        e = _parse_iso(time_window.get("end"))
        if s:
            epoch_start_ms = int(s.timestamp() * 1000)
        if e:
            epoch_end_ms = int(e.timestamp() * 1000)
    files = _list_files_internal(patient_id, flow, stage, epoch_start_ms, epoch_end_ms)
    if not files:
        return (
            f"No files found for patient_id={patient_id} flow={flow} stage={stage} "
            f"window={time_window}."
        )
    truncated = len(files) > limit
    shown = files[:limit]
    total_bytes = sum(f.size for f in shown)
    lines = [
        f"Patient {patient_id}, flow={flow}, stage={stage}: {len(files)} files"
        + (f" (showing first {limit})" if truncated else ""),
        f"Total size of shown: {total_bytes / 1e6:.1f} MB",
        f"Earliest: {_format_ts(shown[0].filename_epoch_dt)} (epoch_ms={shown[0].filename_epoch_ms})",
        f"Latest:   {_format_ts(shown[-1].filename_epoch_dt)} (epoch_ms={shown[-1].filename_epoch_ms})",
        "",
        "Top files:",
    ]
    for f in shown[:30]:
        lines.append(
            f"  {_format_ts(f.filename_epoch_dt)}  {f.size / 1024:>8.0f} KB  {f.key}"
        )
    if len(shown) > 30:
        lines.append(f"  ... and {len(shown) - 30} more")
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────────
# 4. find_patient_last_upload
# ────────────────────────────────────────────────────────────────────────
@tool(
    name="find_patient_last_upload",
    description=(
        "Return the most recent rearrangement upload for a patient. Without "
        "the optional `flow`, scans all 8 flows in parallel and reports the "
        "single latest one across them. With `flow`, scans only that flow. "
        "Cheap — uses S3 LIST + tight prefix; no Athena."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "patient_id": {"type": "integer"},
            "flow": {
                "type": "string",
                "enum": list(KNOWN_FLOWS),
                "description": "Optional. If omitted, scans all flows.",
            },
        },
        "required": ["patient_id"],
    },
)
def find_patient_last_upload(patient_id: int, flow: str | None = None) -> str:
    flows_to_scan = (flow,) if flow else KNOWN_FLOWS
    results: dict[str, FileInfo | None] = {}

    def _last_in_flow(f: str) -> tuple[str, FileInfo | None]:
        try:
            files = _list_files_internal(patient_id, f, "rearrangement")
        except Exception:
            return f, None
        return f, (files[-1] if files else None)

    with ThreadPoolExecutor(max_workers=min(8, len(flows_to_scan))) as pool:
        for fut in as_completed(pool.submit(_last_in_flow, f) for f in flows_to_scan):
            f, last = fut.result()
            results[f] = last

    nonempty = {k: v for k, v in results.items() if v}
    if not nonempty:
        return f"No rearrangement uploads found for patient_id={patient_id} (scanned: {list(results)})."

    # Pick globally latest
    latest_flow, latest_file = max(nonempty.items(), key=lambda kv: kv[1].filename_epoch_ms)
    lines = [
        f"Patient {patient_id} — most recent upload: flow={latest_flow}",
        f"  recorded at: {_format_ts(latest_file.filename_epoch_dt)} (epoch_ms={latest_file.filename_epoch_ms})",
        f"  key:         {latest_file.key}",
        f"  size:        {latest_file.size / 1024:.1f} KB",
        "",
        "Per-flow latest (rearrangement):",
    ]
    for f in flows_to_scan:
        last = results.get(f)
        if last:
            lines.append(f"  {f:18s} {_format_ts(last.filename_epoch_dt)}  {last.key}")
        else:
            lines.append(f"  {f:18s} (no files)")
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────────
# 5. patient_usage_summary
# ────────────────────────────────────────────────────────────────────────
@tool(
    name="patient_usage_summary",
    description=(
        "Per-day file count + total bytes for a patient over the last `days` "
        "days. Uses filename epoch_ms only — no probe, no Athena. Cheap "
        "(one S3 LIST per flow). With `flow`, scans only that flow; without, "
        "scans all 8 flows."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "patient_id": {"type": "integer"},
            "flow": {"type": "string", "enum": list(KNOWN_FLOWS)},
            "days": {"type": "integer", "default": 30, "minimum": 1, "maximum": 365},
        },
        "required": ["patient_id"],
    },
)
def patient_usage_summary(
    patient_id: int, flow: str | None = None, days: int = 30
) -> str:
    cfg = default_flows()
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    epoch_start_ms = int(start.timestamp() * 1000)
    flows_to_scan = (flow,) if flow else KNOWN_FLOWS
    chunk_min = {f: cfg[f].estimated_chunk_duration_min for f in flows_to_scan if f in cfg}

    def _files_for(f: str) -> tuple[str, list[FileInfo]]:
        try:
            return f, _list_files_internal(patient_id, f, "rearrangement", epoch_start_ms)
        except Exception:
            return f, []

    by_flow: dict[str, list[FileInfo]] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(flows_to_scan))) as pool:
        for fut in as_completed(pool.submit(_files_for, f) for f in flows_to_scan):
            f, files = fut.result()
            by_flow[f] = files

    lines = [f"Usage summary for patient {patient_id}, last {days} days:"]
    for f in flows_to_scan:
        files = by_flow.get(f, [])
        if not files:
            lines.append(f"\n  {f}: no files")
            continue
        per_day: dict[str, list[FileInfo]] = {}
        for fi in files:
            day = fi.filename_epoch_dt.strftime("%Y-%m-%d")
            per_day.setdefault(day, []).append(fi)
        total_bytes = sum(fi.size for fi in files)
        est_min = len(files) * chunk_min.get(f, 0)
        lines.append(
            f"\n  {f}: {len(files)} files across {len(per_day)} days, "
            f"{total_bytes / 1e6:.1f} MB total, ~{est_min} min recorded "
            f"(estimate based on {chunk_min.get(f, 0)} min/file heuristic)"
        )
        for day in sorted(per_day, reverse=True)[:14]:
            lst = per_day[day]
            day_bytes = sum(fi.size for fi in lst)
            lines.append(
                f"    {day}: {len(lst):3d} files, {day_bytes / 1e6:5.1f} MB"
            )
        if len(per_day) > 14:
            lines.append(f"    ... and {len(per_day) - 14} more days")
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────────
# 6. merge_patient_window
# ────────────────────────────────────────────────────────────────────────
@tool(
    name="merge_patient_window",
    description=(
        "Download all rearrangement CSV files for a single patient + flow that "
        "overlap with the requested time window, filter rows to the window, "
        "merge into a single CSV (sorted + deduped by sampling_time), upload "
        "to the agent's results bucket, and return a presigned URL for "
        "download. The window must be ≤ 4 hours for sleep_flow and ≤ 24 hours "
        "for the other flows; longer requests are rejected to keep wall-clock "
        "time bounded."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "patient_id": {"type": "integer"},
            "flow": {"type": "string", "enum": list(KNOWN_FLOWS)},
            "start": {"type": "string", "description": "ISO-8601 UTC"},
            "end": {"type": "string", "description": "ISO-8601 UTC"},
        },
        "required": ["patient_id", "flow", "start", "end"],
    },
)
def merge_patient_window(patient_id: int, flow: str, start: str, end: str) -> str:
    if flow not in KNOWN_FLOWS:
        return f"ERROR: unknown flow {flow!r}"
    settings = get_settings()
    output_bucket = settings.output_bucket or settings.athena_results_bucket
    if not output_bucket:
        return (
            "ERROR: no output bucket configured. Set APP_OUTPUT_BUCKET or "
            "APP_ATHENA_RESULTS_BUCKET in environment."
        )
    s_dt = _parse_iso(start)
    e_dt = _parse_iso(end)
    if s_dt is None or e_dt is None or e_dt <= s_dt:
        return "ERROR: invalid start/end ISO timestamps. Use 'YYYY-MM-DDTHH:MM:SSZ'."

    window_hours = (e_dt - s_dt).total_seconds() / 3600
    max_hours = 4.0 if flow == "sleep_flow" else 24.0
    if window_hours > max_hours:
        return (
            f"ERROR: window of {window_hours:.1f} hours exceeds the {max_hours} hour "
            f"limit for flow={flow}. Please narrow the window."
        )

    cfg = default_flows()[flow]
    safety_min = cfg.estimated_chunk_duration_min + cfg.typical_upload_lag_min + 5
    epoch_start_ms = int((s_dt - timedelta(minutes=safety_min)).timestamp() * 1000)
    epoch_end_ms = int((e_dt + timedelta(minutes=safety_min)).timestamp() * 1000)
    files = _list_files_internal(patient_id, flow, "rearrangement", epoch_start_ms, epoch_end_ms)
    if not files:
        return (
            f"No files found for patient {patient_id} flow {flow} between "
            f"{start} and {end} (with {safety_min}-min safety buffer)."
        )

    s3 = get_client("s3")
    result = download_and_merge_inmemory(s3, APP_EVENTS_BUCKET, files, s_dt, e_dt, cfg)
    if result.merged_df.empty:
        return (
            f"Found {len(files)} files in window but merge produced 0 rows after "
            f"sampling_time filter. Verify the window overlaps actual recording time "
            f"by probing one file with probe_file_time_range."
        )
    df = result.merged_df
    out_buf = io.BytesIO()
    df.to_csv(out_buf, index=False)
    out_buf.seek(0)

    output_key = (
        f"agent-merges/patient_{patient_id}/{flow}/"
        f"{s_dt.strftime('%Y%m%dT%H%M%SZ')}_{e_dt.strftime('%Y%m%dT%H%M%SZ')}.csv"
    )
    s3.put_object(
        Bucket=output_bucket,
        Key=output_key,
        Body=out_buf.getvalue(),
        ContentType="text/csv",
    )
    presigned_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": output_bucket, "Key": output_key},
        ExpiresIn=3600,
    )
    return (
        f"Merged {result.files_with_data}/{result.files_downloaded} files into "
        f"{len(df):,} rows.\n"
        f"Output: s3://{output_bucket}/{output_key}\n"
        f"Presigned URL (1 hour): {presigned_url}\n"
        f"Window: {start} → {end} ({window_hours:.2f}h)"
    )
