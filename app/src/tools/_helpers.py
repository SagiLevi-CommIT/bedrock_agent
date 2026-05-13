"""Shared helpers for Athena polling and formatting."""

from __future__ import annotations

import time
from typing import Any

from ..settings import get_client, get_settings


def athena_select_rows(
    sql: str,
    *,
    database: str | None = None,
    timeout_s: float = 60.0,
    max_rows: int | None = None,
) -> tuple[str, int, list[list[str]]]:
    """Run SQL on Athena; return (query_id, scanned_bytes, rows as cell lists).

    First row is the header when present.
    """
    s = get_settings()
    athena = get_client("athena")
    db = database or s.athena_default_database
    output = f"s3://{s.athena_results_bucket}/" if s.athena_results_bucket else None
    cap = max_rows if max_rows is not None else s.athena_max_rows

    start_kwargs: dict[str, Any] = {
        "QueryString": sql,
        "QueryExecutionContext": {"Database": db},
        "WorkGroup": s.athena_workgroup,
    }
    if output:
        start_kwargs["ResultConfiguration"] = {"OutputLocation": output}

    qid = athena.start_query_execution(**start_kwargs)["QueryExecutionId"]
    deadline = time.time() + timeout_s
    info: dict[str, Any] = {}
    while time.time() < deadline:
        info = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
        state = info["Status"]["State"]
        if state in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            break
        time.sleep(1.0)

    state = info["Status"]["State"]
    if state != "SUCCEEDED":
        reason = info["Status"].get("StateChangeReason", "(no reason)")
        raise RuntimeError(f"Athena query {qid} ended in state {state}: {reason}")

    scanned = int(info.get("Statistics", {}).get("DataScannedInBytes", 0) or 0)
    rows_pages = athena.get_paginator("get_query_results").paginate(
        QueryExecutionId=qid, PaginationConfig={"PageSize": 200}
    )
    out_rows: list[list[str]] = []
    for page in rows_pages:
        for r in page["ResultSet"]["Rows"]:
            out_rows.append([c.get("VarCharValue", "") for c in r.get("Data", [])])
        if len(out_rows) >= cap + 1:
            break
    return qid, scanned, out_rows


def human_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    x = float(n)
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        x /= 1024.0
        if x < 1024.0 or unit == "TiB":
            return f"{x:.1f} {unit}"
    return f"{x:.1f} TiB"


def scan_cost_usd(bytes_scanned: int, cost_per_tb_usd: float) -> float:
    # Athena list pricing uses decimal TB (1 TB = 1e12 bytes).
    return (bytes_scanned / 1e12) * cost_per_tb_usd
