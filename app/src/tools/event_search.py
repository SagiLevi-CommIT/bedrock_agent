"""Cross-reference Cardiolyse annotations (Athena) with rt_flow files in S3."""

from __future__ import annotations

from datetime import timedelta

from . import app_events as ae
from . import tool
from .patient_resolver import resolve_patient_uuid
from ._helpers import athena_select_rows


def _resolve_uuid_line(patient_id: int) -> str | None:
    """Return UUID string from resolver tool output or None."""
    text = resolve_patient_uuid(patient_id, force_refresh=False)
    if text.startswith("ERROR"):
        return None
    for line in text.splitlines():
        if "pUuid:" in line or "pUuid" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                u = parts[1].strip()
                if len(u) > 30 and "-" in u:
                    return u
    return None


@tool(
    name="search_files_with_arrhythmia_events",
    description=(
        "For one patient, find rt_flow rearrangement files in a UTC window that "
        "overlap periods with Cardiolyse annotations matching the given label "
        "(uses migrated_data.pc_timeseries with date partition filter). "
        "Refuses cross-patient scans when the window is longer than 6 hours."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "arrhythmia_label": {"type": "string"},
            "start_utc": {"type": "string"},
            "end_utc": {"type": "string"},
            "min_count": {"type": "integer", "default": 1, "minimum": 1},
            "patient_id": {"type": "integer"},
            "patient_uuid": {"type": "string"},
            "max_files": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
        },
        "required": ["arrhythmia_label", "start_utc", "end_utc"],
    },
)
def search_files_with_arrhythmia_events(
    arrhythmia_label: str,
    start_utc: str,
    end_utc: str,
    min_count: int = 1,
    patient_id: int | None = None,
    patient_uuid: str | None = None,
    max_files: int = 50,
) -> str:
    s_start = ae._parse_iso(start_utc)
    s_end = ae._parse_iso(end_utc)
    if s_start is None or s_end is None or s_end <= s_start:
        return "ERROR: invalid start_utc/end_utc."

    if patient_id is None and not patient_uuid:
        span = s_end - s_start
        if span > timedelta(hours=6):
            return (
                "ERROR: without patient_id, window must be ≤ 6 hours "
                f"(got {span}). Narrow the range or pass patient_id."
            )

    uuid = patient_uuid
    if uuid is None and patient_id is not None:
        uuid = _resolve_uuid_line(int(patient_id))
        if uuid is None:
            return "ERROR: could not resolve patient_id to UUID; fix resolver env/cache."

    matched = annotation_sql_in_clause(arrhythmia_label)
    if not matched:
        return (
            f"ERROR: unknown arrhythmia_label {arrhythmia_label!r}. "
            "Call list_arrhythmia_labels first."
        )
    _display, in_clause = matched

    d_start = s_start.date().isoformat()
    d_end = s_end.date().isoformat()

    s = get_settings()
    if not uuid:
        return "ERROR: patient_uuid required after resolution."

    sql = f"""
SELECT COUNT(*) AS c
FROM migrated_data.pc_timeseries
WHERE patient = '{uuid}'
  AND date BETWEEN DATE '{d_start}' AND DATE '{d_end}'
  AND CAST(sampling_time AS BIGINT) >= {int(s_start.timestamp() * 1000)}
  AND CAST(sampling_time AS BIGINT) <= {int(s_end.timestamp() * 1000)}
  AND `crlyse-annotation` IN ({in_clause})
""".strip()

    try:
        qid, scanned, rows = athena_select_rows(sql, timeout_s=90.0, max_rows=10)
    except Exception as e:  # noqa: BLE001
        return f"ERROR: Athena: {type(e).__name__}: {e}"

    count = 0
    if len(rows) >= 2:
        try:
            count = int(rows[1][0])
        except (ValueError, IndexError):
            count = 0

    if count < min_count:
        return (
            f"Found {count} matching samples (min_count={min_count}). "
            f"query_id={qid} scanned_bytes={scanned}. Label={arrhythmia_label!r}."
        )

    if patient_id is None:
        return (
            f"Matched {count} annotated samples in pc_timeseries but patient_id "
            f"is required to list rt_flow files. query_id={qid} scanned_bytes={scanned}"
        )

    epoch_start_ms = int((s_start - timedelta(minutes=30)).timestamp() * 1000)
    epoch_end_ms = int((s_end + timedelta(minutes=30)).timestamp() * 1000)
    files = ae._list_files_internal(
        int(patient_id), "rt_flow", "rearrangement", epoch_start_ms, epoch_end_ms
    )
    files = files[:max_files]

    lines = [
        f"annotation_samples={count} (min_count={min_count}) query_id={qid} scanned_bytes={scanned}",
        f"rt_flow files in window (cap {max_files}): {len(files)}",
        "",
    ]
    for f in files[:50]:
        lines.append(f"  {ae._format_ts(f.filename_epoch_dt)}  {f.size / 1024:.0f} KB  {f.key}")
    if len(files) > 50:
        lines.append(f"  ... and {len(files) - 50} more")
    return "\n".join(lines)
