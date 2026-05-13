"""Presigned-URL generator for the CardiacSense data buckets + agent results.

Read-only: only generates URLs for `get_object`. Bucket allowlist enforced —
the model cannot generate URLs for arbitrary buckets even if it asks.
"""
from __future__ import annotations

from ..settings import get_client, get_settings
from . import tool

DATA_BUCKETS_ALLOWLIST: tuple[str, ...] = (
    "735555370207-app-events",
    "735555370207-migrated--data",
    "735555370207-datasets-versioning",
)


@tool(
    name="presign_s3_object",
    description=(
        "Generate a read-only presigned URL for an S3 object so the user can "
        "download a single file via HTTP. Allowed buckets: the three "
        "CardiacSense data buckets + the agent's own output bucket. Default "
        "expiry is 1 hour; max 24 hours. Use this whenever the user asks for "
        "a download link to a specific file (e.g. a rearrangement CSV, a "
        "post-computation JSON summary, or a merged output)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "bucket": {"type": "string"},
            "key": {"type": "string"},
            "expires_in": {
                "type": "integer",
                "default": 3600,
                "minimum": 60,
                "maximum": 86400,
            },
        },
        "required": ["bucket", "key"],
    },
)
def presign_s3_object(bucket: str, key: str, expires_in: int = 3600) -> str:
    settings = get_settings()
    allowed = set(DATA_BUCKETS_ALLOWLIST)
    if settings.output_bucket:
        allowed.add(settings.output_bucket)
    if settings.athena_results_bucket:
        allowed.add(settings.athena_results_bucket)
    if bucket not in allowed:
        return (
            f"ERROR: bucket {bucket!r} not in allowlist. Allowed: "
            f"{sorted(allowed)}"
        )
    if not key or key.endswith("/"):
        return f"ERROR: invalid key {key!r}"
    s3 = get_client("s3")
    try:
        # HEAD first so the model gets a clear error if the key doesn't exist,
        # rather than a URL that 404s on click.
        head = s3.head_object(Bucket=bucket, Key=key)
    except Exception as e:  # noqa: BLE001
        return f"ERROR: head_object failed for s3://{bucket}/{key}: {type(e).__name__}: {e}"
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_in,
    )
    return (
        f"Presigned URL (expires in {expires_in}s):\n{url}\n\n"
        f"Object: s3://{bucket}/{key}\n"
        f"Size:   {head['ContentLength']:,} bytes\n"
        f"LastModified: {head['LastModified'].isoformat()}\n"
        f"This is a read-only link — anyone with it can download for the next "
        f"{expires_in} seconds."
    )
