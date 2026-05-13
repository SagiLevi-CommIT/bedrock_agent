"""Athena scan-size estimator via Glue catalog + partition metadata."""

from __future__ import annotations

import json
import re
from typing import Any

from ..audit import log_event
from ..settings import get_client, get_settings
from . import tool
from ._helpers import human_bytes, scan_cost_usd

# FROM db.table | FROM table | JOIN db.table
_FROM_JOIN = re.compile(
    r"\b(?:FROM|JOIN)\s+((?:`?[\w]+`?\.)?`?[\w]+`?)",
    re.IGNORECASE,
)
# partition_col = 'literal' or = "literal" or = DATE '...'
_EQ = re.compile(
    r"([\w`]+)\s*=\s*(?:DATE\s+)?'([^']+)'",
    re.IGNORECASE,
)
_EQ_DQ = re.compile(r'([\w`]+)\s*=\s*"([^"]+)"', re.IGNORECASE)
_IN = re.compile(
    r"([\w`]+)\s+IN\s*\(\s*((?:'[^']*'(?:\s*,\s*)?)+)\s*\)",
    re.IGNORECASE,
)
_BETWEEN = re.compile(
    r"([\w`]+)\s+BETWEEN\s+(?:DATE\s+)?'([^']+)'\s+AND\s+(?:DATE\s+)?'([^']+)'",
    re.IGNORECASE,
)


def _strip_ident(s: str) -> str:
    return s.strip().strip("`").strip()


def _parse_table_ref(raw: str, default_db: str) -> tuple[str, str]:
    t = _strip_ident(raw)
    if "." in t:
        db, name = t.split(".", 1)
        return _strip_ident(db), _strip_ident(name)
    return default_db, t


def _extract_tables(sql: str, default_db: str) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for m in _FROM_JOIN.finditer(sql):
        ref = m.group(1)
        if ref.upper() in {"SELECT", "WITH", "UNNEST"}:
            continue
        db, name = _parse_table_ref(ref, default_db)
        key = (db.lower(), name.lower())
        if key not in seen:
            seen.add(key)
            out.append((db, name))
    return out


def _partition_predicates(sql: str, partition_keys: list[str]) -> dict[str, list[str]]:
    """Map partition column -> list of literal values inferred from WHERE."""
    keys_lower = {k.lower(): k for k in partition_keys}
    found: dict[str, set[str]] = {}

    def add(col: str, vals: list[str]) -> None:
        c = _strip_ident(col)
        lk = c.lower()
        if lk not in keys_lower:
            return
        canon = keys_lower[lk]
        found.setdefault(canon, set()).update(vals)

    for m in _EQ.finditer(sql):
        add(m.group(1), [m.group(2)])
    for m in _EQ_DQ.finditer(sql):
        add(m.group(1), [m.group(2)])
    for m in _IN.finditer(sql):
        inner = m.group(2)
        vals = re.findall(r"'([^']*)'", inner)
        add(m.group(1), vals)
    for m in _BETWEEN.finditer(sql):
        # Expand date range crudely: only if looks like YYYY-MM-DD
        a, b = m.group(2), m.group(3)
        add(m.group(1), [a, b])

    return {k: sorted(v) for k, v in found.items()}


def _glue_expression(partition_keys: list[str], preds: dict[str, list[str]]) -> str | None:
    """Build Glue get_partitions Expression (partition cols only)."""
    parts: list[str] = []
    for pk in partition_keys:
        if pk not in preds:
            continue
        vals = preds[pk]
        if not vals:
            continue
        if len(vals) == 1:
            parts.append(f"{pk}='{vals[0]}'")
        elif len(vals) == 2:
            # BETWEEN heuristic for dates
            parts.append(f"{pk}>='{vals[0]}' AND {pk}<='{vals[1]}'")
        else:
            in_list = ",".join(f"'{v}'" for v in vals[:50])
            parts.append(f"{pk} IN ({in_list})")
    if not parts:
        return None
    return " AND ".join(parts)


def _sum_partition_bytes(
    glue: Any,
    database: str,
    table: str,
    expression: str | None,
    max_pages: int = 5,
) -> tuple[int, int, str]:
    """Return (total_bytes, partition_count, coverage)."""
    total = 0
    count = 0
    paginator = glue.get_paginator("get_partitions")
    kwargs: dict[str, Any] = {
        "DatabaseName": database,
        "TableName": table,
        "PaginationConfig": {"PageSize": 100},
    }
    if expression:
        kwargs["Expression"] = expression
    pages = 0
    for page in paginator.paginate(**kwargs):
        pages += 1
        for p in page.get("Partitions", []):
            count += 1
            params = p.get("Parameters") or {}
            ts = params.get("totalSize") or params.get("transient_lastDdlTime")
            if ts and str(ts).isdigit():
                total += int(ts)
        if pages >= max_pages:
            break
    if expression:
        cov = "full" if pages < max_pages else "partial"
    else:
        cov = "none" if count == 0 else ("partial" if pages >= max_pages else "full")
    return total, count, cov


def estimate_scan_for_sql(sql: str, database: str | None = None) -> dict[str, Any]:
    """Core estimator used by tool and run_athena_query."""
    s = get_settings()
    db_default = database or s.athena_default_database
    glue = get_client("glue")
    tables = _extract_tables(sql, db_default)
    if not tables:
        return {
            "estimate_bytes": 0,
            "estimate_cost_usd": 0.0,
            "partition_coverage": "unknown",
            "target_table": "",
            "matched_partitions": 0,
            "notes": "No FROM/JOIN tables found in SQL.",
        }

    # Primary target: first physical table in FROM clause
    target_db, target_name = tables[0]
    try:
        tbl = glue.get_table(DatabaseName=target_db, Name=target_name)["Table"]
    except Exception as e:  # noqa: BLE001
        return {
            "estimate_bytes": 0,
            "estimate_cost_usd": 0.0,
            "partition_coverage": "unknown",
            "target_table": f"{target_db}.{target_name}",
            "matched_partitions": 0,
            "notes": f"Glue get_table failed: {type(e).__name__}: {e}",
        }

    pkeys = [p["Name"] for p in tbl.get("PartitionKeys", [])]
    preds = _partition_predicates(sql, pkeys)
    expr = _glue_expression(pkeys, preds)

    total_bytes, pcount, cov = _sum_partition_bytes(glue, target_db, target_name, expr)
    notes_parts: list[str] = []

    if total_bytes == 0 and pkeys:
        # Stats missing — try unfiltered capped sample; err high
        raw_total, raw_count, raw_cov = _sum_partition_bytes(
            glue, target_db, target_name, None, max_pages=5
        )
        if raw_total > 0:
            notes_parts.append(
                f"Partition size stats sparse; summed {raw_count} partitions "
                f"(capped pages) without filter → {human_bytes(raw_total)}."
            )
            if expr:
                cov = "unknown"
                total_bytes = raw_total * 4
                notes_parts.append(
                    "Inflated x4 as conservative stand-in when filtered size unknown."
                )
            else:
                total_bytes = raw_total
                cov = raw_cov
        else:
            sd = tbl.get("StorageDescriptor") or {}
            loc = sd.get("Location") or ""
            notes_parts.append(
                f"No totalSize in partition metadata; location={loc!r}. "
                "Treating as unknown scan size → conservative block."
            )
            cov = "unknown"
            total_bytes = 10 * 1024**3

    if not pkeys:
        cov = "none"
        sd = tbl.get("StorageDescriptor") or {}
        params = sd.get("Parameters") or {}
        notes_parts.append("Table has no partition keys in Glue; full table scan likely.")
        if not notes_parts or total_bytes == 0:
            total_bytes = int(params.get("sizeKey", 0) or 0) or (5 * 1024**3)

    cost = scan_cost_usd(total_bytes, s.athena_cost_per_tb_usd)
    log_event(
        "agent.tool_trace",
        "estimate_athena_scan_internal",
        target=f"{target_db}.{target_name}",
        estimate_bytes=total_bytes,
        partition_coverage=cov,
        partitions=pcount,
    )

    return {
        "estimate_bytes": int(total_bytes),
        "estimate_cost_usd": round(cost, 6),
        "partition_coverage": cov,
        "target_table": f"{target_db}.{target_name}",
        "matched_partitions": pcount,
        "notes": " ".join(notes_parts).strip(),
    }


@tool(
    name="estimate_athena_scan",
    description=(
        "Estimate Athena bytes to be scanned for a SELECT/WITH query using "
        "Glue table metadata and partition statistics. Call BEFORE "
        "run_athena_query when partition coverage is uncertain. Returns JSON "
        "with estimate_bytes, estimate_cost_usd (at $5/TB default), "
        "partition_coverage (full|partial|none|unknown), target_table, "
        "matched_partitions, notes."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sql": {"type": "string"},
            "database": {"type": "string", "description": "Athena database default if SQL uses unqualified tables."},
        },
        "required": ["sql"],
    },
)
def estimate_athena_scan(sql: str, database: str | None = None) -> str:
    est = estimate_scan_for_sql(sql, database=database)
    return json.dumps(est, indent=2)
