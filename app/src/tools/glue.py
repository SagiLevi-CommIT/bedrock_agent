"""Glue catalog tools, ported from claude_aws_agent/tools/glue_catalog.py."""
from __future__ import annotations

import json

from ..settings import get_client
from . import tool


def _paginate(glue, method: str, key: str, **kwargs) -> list:
    items = []
    paginator = glue.get_paginator(method)
    for page in paginator.paginate(**kwargs):
        items.extend(page.get(key, []))
    return items


@tool(
    name="list_databases",
    description="List all Glue catalog databases.",
    input_schema={"type": "object", "properties": {}, "required": []},
)
def list_databases() -> str:
    glue = get_client("glue")
    dbs = _paginate(glue, "get_databases", "DatabaseList")
    if not dbs:
        return "No Glue databases found."
    lines = [f"Glue databases ({len(dbs)}):"]
    for db in sorted(dbs, key=lambda d: d["Name"]):
        desc = db.get("Description") or ""
        lines.append(f"  {db['Name']}" + (f"  -- {desc}" if desc else ""))
    return "\n".join(lines)


@tool(
    name="list_tables",
    description="List all tables in a Glue database with column count, partitions, and S3 location.",
    input_schema={
        "type": "object",
        "properties": {
            "database": {"type": "string", "description": "Glue database name."}
        },
        "required": ["database"],
    },
)
def list_tables(database: str) -> str:
    glue = get_client("glue")
    tables = _paginate(glue, "get_tables", "TableList", DatabaseName=database)
    if not tables:
        return f"No tables found in database '{database}'."
    lines = [f"Tables in '{database}' ({len(tables)}):"]
    for t in sorted(tables, key=lambda x: x["Name"]):
        cols = t.get("StorageDescriptor", {}).get("Columns", [])
        parts = t.get("PartitionKeys", [])
        loc = t.get("StorageDescriptor", {}).get("Location", "")
        part_str = f"  parts=[{','.join(p['Name'] for p in parts)}]" if parts else "  NO_PARTITIONS"
        lines.append(f"  {t['Name']}  cols={len(cols)}{part_str}  loc={loc}")
    return "\n".join(lines)


@tool(
    name="describe_table",
    description="Return full schema (columns, types, partitions, S3 location, SerDe) for a Glue table.",
    input_schema={
        "type": "object",
        "properties": {
            "database": {"type": "string"},
            "table": {"type": "string"},
        },
        "required": ["database", "table"],
    },
)
def describe_table(database: str, table: str) -> str:
    glue = get_client("glue")
    try:
        resp = glue.get_table(DatabaseName=database, Name=table)
    except glue.exceptions.EntityNotFoundException:
        return f"Table '{database}.{table}' not found."
    tbl = resp["Table"]
    sd = tbl.get("StorageDescriptor", {})
    info = {
        "database": database,
        "table": tbl["Name"],
        "location": sd.get("Location", ""),
        "serde": sd.get("SerdeInfo", {}).get("SerializationLibrary", ""),
        "columns": [{"name": c["Name"], "type": c["Type"]} for c in sd.get("Columns", [])],
        "partition_keys": [
            {"name": p["Name"], "type": p["Type"]} for p in tbl.get("PartitionKeys", [])
        ],
    }
    return json.dumps(info, indent=2)


@tool(
    name="search_tables",
    description="Search across all databases for tables whose name contains the given term (case-insensitive).",
    input_schema={
        "type": "object",
        "properties": {
            "term": {"type": "string", "description": "Substring to match in table names."}
        },
        "required": ["term"],
    },
)
def search_tables(term: str) -> str:
    glue = get_client("glue")
    dbs = _paginate(glue, "get_databases", "DatabaseList")
    needle = term.lower()
    matches: list[str] = []
    for db in dbs:
        db_name = db["Name"]
        try:
            tables = _paginate(glue, "get_tables", "TableList", DatabaseName=db_name)
        except Exception:
            continue
        for t in tables:
            if needle in t["Name"].lower():
                parts = t.get("PartitionKeys", [])
                loc = t.get("StorageDescriptor", {}).get("Location", "")
                p = f"parts=[{','.join(x['Name'] for x in parts)}]" if parts else "NO_PARTS"
                matches.append(f"  {db_name}.{t['Name']}  {p}  loc={loc}")
    if not matches:
        return f"No tables matching '{term}' found."
    return f"Tables matching '{term}' ({len(matches)}):\n" + "\n".join(matches)
