"""S3 listing/browsing tool, ported from claude_aws_agent/tools/s3_explore.py.

Limited to read-only list operations. The data buckets are scoped via the IAM
task role so the model cannot browse arbitrary buckets even if it tries.
"""
from __future__ import annotations

from ..settings import get_client
from . import tool


@tool(
    name="explore_s3",
    description=(
        "List sub-prefixes and objects under an S3 prefix. action='list' returns "
        "a tree-style summary; action='objects' returns object keys with size and "
        "last-modified. Use only on the CardiacSense data buckets."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "bucket": {"type": "string"},
            "prefix": {"type": "string", "description": "S3 prefix; '' for root.", "default": ""},
            "action": {"type": "string", "enum": ["list", "objects"], "default": "list"},
            "max_keys": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
        },
        "required": ["bucket"],
    },
)
def explore_s3(bucket: str, prefix: str = "", action: str = "list", max_keys: int = 100) -> str:
    s3 = get_client("s3")
    paginator = s3.get_paginator("list_objects_v2")

    if action == "objects":
        lines = [f"Bucket: {bucket}  Prefix: {prefix or '(root)'}"]
        count = 0
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix, MaxKeys=max_keys):
            for obj in page.get("Contents", []):
                size_kb = round(obj["Size"] / 1024, 1)
                modified = obj["LastModified"].strftime("%Y-%m-%d %H:%M:%S")
                lines.append(f"  {obj['Key']}  ({size_kb} KB, {modified})")
                count += 1
                if count >= max_keys:
                    break
            if count >= max_keys:
                break
        lines.insert(1, f"Objects: {count}")
        return "\n".join(lines)

    prefixes: list[str] = []
    objects: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/", MaxKeys=max_keys):
        for cp in page.get("CommonPrefixes", []):
            prefixes.append(cp["Prefix"])
        for obj in page.get("Contents", []):
            objects.append(obj["Key"])

    lines = [f"Bucket: {bucket}  Prefix: {prefix or '(root)'}"]
    if prefixes:
        lines.append(f"\nSub-prefixes ({len(prefixes)}):")
        lines.extend(f"  {p}" for p in prefixes[:50])
        if len(prefixes) > 50:
            lines.append(f"  ... and {len(prefixes) - 50} more")
    if objects:
        lines.append(f"\nObjects ({len(objects)}):")
        lines.extend(f"  {o}" for o in objects[:30])
        if len(objects) > 30:
            lines.append(f"  ... and {len(objects) - 30} more")
    if not prefixes and not objects:
        lines.append("(empty)")
    return "\n".join(lines)
