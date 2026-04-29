"""Athena query tool, ported from claude_aws_agent/tools/athena_query.py.

Preserves the read-only enforcement and auto-LIMIT 1000 guardrails. Date-type
auto-correction (DATE vs STRING partitions) is intentionally elided in v1
because the table-set is small and the model can be prompted to use the right
literal form via the system prompt + knowledge files in Phase 4.
"""
from __future__ import annotations

import re
import time

from ..settings import get_client, get_settings
from . import tool

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
        "tables (e.g. `migrated_data.pc_results_part`, `migrated_data.timeseries`) "
        "by their `date` partition; missing the filter triggers a full table "
        "scan and is expensive."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "Read-only SQL."},
            "database": {"type": "string", "description": "Default Athena database (optional)."},
        },
        "required": ["sql"],
    },
)
def run_athena_query(sql: str, database: str | None = None) -> str:
    s = get_settings()
    safety = _ensure_safe(sql)
    if safety:
        return safety
    final_sql = _ensure_limit(sql, s.athena_max_rows)

    athena = get_client("athena")
    db = database or s.athena_default_database
    output = (
        f"s3://{s.athena_results_bucket}/" if s.athena_results_bucket else None
    )

    start_kwargs: dict = {
        "QueryString": final_sql,
        "QueryExecutionContext": {"Database": db},
        "WorkGroup": s.athena_workgroup,
    }
    if output:
        start_kwargs["ResultConfiguration"] = {"OutputLocation": output}

    qid = athena.start_query_execution(**start_kwargs)["QueryExecutionId"]

    deadline = time.time() + 60
    state = "RUNNING"
    while time.time() < deadline:
        info = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
        state = info["Status"]["State"]
        if state in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            break
        time.sleep(1.0)

    if state != "SUCCEEDED":
        reason = info["Status"].get("StateChangeReason", "(no reason)")
        return f"Athena query {qid} ended in state {state}: {reason}"

    scanned = info["Statistics"].get("DataScannedInBytes", 0)
    rows_pages = athena.get_paginator("get_query_results").paginate(
        QueryExecutionId=qid, PaginationConfig={"PageSize": 200}
    )
    out_rows: list[list[str]] = []
    for page in rows_pages:
        for r in page["ResultSet"]["Rows"]:
            out_rows.append([c.get("VarCharValue", "") for c in r.get("Data", [])])
        if len(out_rows) >= s.athena_max_rows + 1:
            break

    if not out_rows:
        return f"Query {qid} returned no rows. (scanned: {scanned} bytes, sql: {final_sql})"

    header = out_rows[0]
    body = out_rows[1:]
    preview_n = min(len(body), 50)
    preview_lines = ["\t".join(header)] + ["\t".join(r) for r in body[:preview_n]]
    extra = f"\n... ({len(body) - preview_n} more rows)" if len(body) > preview_n else ""
    return (
        f"query_id={qid}\nrows_returned={len(body)}  scanned_bytes={scanned}\n"
        f"sql:\n  {final_sql}\n\n" + "\n".join(preview_lines) + extra
    )
