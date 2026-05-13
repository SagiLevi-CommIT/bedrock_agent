"""Athena query tool, ported from claude_aws_agent/tools/athena_query.py.

Preserves read-only enforcement, auto-LIMIT, and adds a scan-size guard via
``estimate_athena_scan`` + ``confirm_heavy_scan``.
"""
from __future__ import annotations

import re
import time

from ..settings import get_client, get_settings
from . import tool
from ._helpers import athena_select_rows, human_bytes, scan_cost_usd
from .estimator import estimate_scan_for_sql

_BLOCKED = re.compile(
    r"\b(DROP\s+TABLE|CREATE\s+TABLE|CREATE\s+EXTERNAL|ALTER|INSERT|UPDATE|DELETE|TRUNCATE|MERGE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)
_VIEW_DDL = re.compile(r"^\s*(CREATE\s+(OR\s+REPLACE\s+)?VIEW|DROP\s+VIEW)\s+", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\blimit\s+\d+\b", re.IGNORECASE)
_TRAILING_SEMICOLON = re.compile(r";\s*$")


def _ensure_safe(sql: str) -> str | None:
    if _BLOCKED.search(sql):
        return "ERROR: write/DDL statements are blocked. Read-only SQL only."
    if _VIEW_DDL.search(sql):
        return "ERROR: view DDL is not allowed in this build."
    return None


def _ensure_limit(sql: str, max_rows: int) -> str:
    cleaned = _TRAILING_SEMICOLON.sub("", sql).strip()
    if _LIMIT_RE.search(cleaned):
        return cleaned
    if cleaned.lower().lstrip().startswith(("select", "with")):
        return f"{cleaned}\nLIMIT {max_rows}"
    return cleaned


@tool(
    name="run_athena_query",
    description=(
        "Execute a read-only SQL query against Amazon Athena and return up to "
        "1000 rows. Only SELECT/WITH/DESCRIBE/SHOW are allowed; an automatic "
        "LIMIT is appended if the query lacks one. Always filter partitioned "
        "tables by their date partition. If the estimated scan exceeds the "
        "default threshold (ATHENA_MAX_SCAN_GB_DEFAULT, default 1 GB), the "
        "tool returns a BLOCKED message — call again with "
        "confirm_heavy_scan=true only after the user explicitly confirms."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "Read-only SQL."},
            "database": {"type": "string", "description": "Default Athena database (optional)."},
            "confirm_heavy_scan": {
                "type": "boolean",
                "default": False,
                "description": "Set true only after user confirms a heavy scan.",
            },
            "max_scan_gb": {
                "type": "number",
                "description": "Override scan threshold in GB (optional).",
            },
        },
        "required": ["sql"],
    },
)
def run_athena_query(
    sql: str,
    database: str | None = None,
    confirm_heavy_scan: bool = False,
    max_scan_gb: float | None = None,
) -> str:
    s = get_settings()
    safety = _ensure_safe(sql)
    if safety:
        return safety
    final_sql = _ensure_limit(sql, s.athena_max_rows)

    est = estimate_scan_for_sql(final_sql, database=database)
    est_bytes = int(est.get("estimate_bytes", 0) or 0)
    threshold_gb = float(max_scan_gb) if max_scan_gb is not None else float(s.athena_max_scan_gb_default)
    est_gb = est_bytes / 1e9
    cov = est.get("partition_coverage", "unknown")
    target = est.get("target_table", "")
    cost_usd = float(est.get("estimate_cost_usd", 0) or 0)

    if est_gb > threshold_gb and not confirm_heavy_scan:
        return (
            f"BLOCKED: estimated scan {est_gb:.2f} GB (${cost_usd:.4f}) exceeds threshold "
            f"{threshold_gb:.2f} GB. partition_coverage={cov} target={target}. "
            "Show this to the user verbatim and call again with confirm_heavy_scan=true "
            "after they confirm."
        )

    try:
        qid, scanned, out_rows = athena_select_rows(
            final_sql,
            database=database or s.athena_default_database,
            timeout_s=60.0,
            max_rows=s.athena_max_rows,
        )
    except Exception as e:  # noqa: BLE001
        return f"ERROR: Athena execution failed: {type(e).__name__}: {e}"

    if not out_rows:
        hb = human_bytes(scanned)
        usd = scan_cost_usd(scanned, s.athena_cost_per_tb_usd)
        return f"Query {qid} returned no rows. scanned: {hb} (${usd:.4f})  scanned_bytes={scanned}  sql: {final_sql}"

    header = out_rows[0]
    body = out_rows[1:]
    preview_n = min(len(body), 50)
    preview_lines = ["\t".join(header)] + ["\t".join(r) for r in body[:preview_n]]
    extra = f"\n... ({len(body) - preview_n} more rows)" if len(body) > preview_n else ""
    hb = human_bytes(scanned)
    usd = scan_cost_usd(scanned, s.athena_cost_per_tb_usd)
    return (
        f"query_id={qid}\nrows_returned={len(body)}  scanned: {hb} (${usd:.4f})\n"
        f"scanned_bytes={scanned}\n"
        f"sql:\n  {final_sql}\n\n" + "\n".join(preview_lines) + extra
    )
