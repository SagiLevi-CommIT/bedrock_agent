"""Coverage report from an Athena result set (sampling_time column)."""

from __future__ import annotations

import re

import pandas as pd

from ..lib.cs_downloader.config import default_flows
from ..lib.cs_downloader.gap_detector import build_coverage_report, validate_time_coverage
from ..lib.cs_downloader.time_utils import parse_sampling_time
from . import app_events as ae
from . import tool
from ._helpers import athena_select_rows


@tool(
    name="coverage_report_from_athena",
    description=(
        "Run a read-only Athena SELECT that returns a sampling_time column, "
        "then validate coverage vs [start_utc, end_utc] using flow gap "
        "heuristics (default sleep_flow). Returns a human-readable coverage "
        "report."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "SELECT with sampling_time column."},
            "start_utc": {"type": "string"},
            "end_utc": {"type": "string"},
            "flow": {
                "type": "string",
                "default": "sleep_flow",
                "description": "Flow name for gap heuristics (sleep_flow, rt_flow, ...).",
            },
            "database": {"type": "string"},
        },
        "required": ["sql", "start_utc", "end_utc"],
    },
)
def coverage_report_from_athena(
    sql: str,
    start_utc: str,
    end_utc: str,
    flow: str = "sleep_flow",
    database: str | None = None,
) -> str:
    user_start = ae._parse_iso(start_utc)
    user_end = ae._parse_iso(end_utc)
    if user_start is None or user_end is None or user_end <= user_start:
        return "ERROR: invalid start_utc/end_utc."

    flows = default_flows()
    if flow not in flows:
        return f"ERROR: unknown flow {flow!r}. Known: {sorted(flows)}"
    cfg = flows[flow]

    s = get_settings()
    try:
        qid, scanned, rows = athena_select_rows(
            sql,
            database=database or s.athena_default_database,
            timeout_s=90.0,
            max_rows=50_000,
        )
    except Exception as e:  # noqa: BLE001
        return f"ERROR: Athena failed: {type(e).__name__}: {e}"

    if len(rows) < 2:
        return f"Query {qid} returned no data rows. scanned_bytes={scanned}"

    header = [h.strip() for h in rows[0]]
    col_idx = None
    for i, h in enumerate(header):
        if h.lower() == "sampling_time":
            col_idx = i
            break
    if col_idx is None:
        fuzzy = [c for c in header if re.search(r"sampling.?time", c, re.I)]
        if len(fuzzy) == 1:
            col_idx = header.index(fuzzy[0])
    if col_idx is None:
        return (
            f"ERROR: no sampling_time column in result. Columns: {header}. "
            f"query_id={qid} scanned_bytes={scanned}"
        )

    raw_vals: list[str] = []
    for r in rows[1:]:
        if col_idx < len(r):
            raw_vals.append(r[col_idx])
    ser = parse_sampling_time(pd.Series(raw_vals))
    ser = ser.dropna().sort_values()
    if ser.empty:
        return f"No parseable sampling_time values. query_id={qid} scanned_bytes={scanned}"

    val = validate_time_coverage(ser, user_start, user_end, cfg, next_file_start=None)
    report = build_coverage_report(val)
    return f"query_id={qid} scanned_bytes={scanned}\n\n{report}"
