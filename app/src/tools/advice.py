"""Write per-session self-reflection markdown to the agent output bucket."""

from __future__ import annotations

from datetime import datetime, timezone

from ..session_context import session_id_ctx
from ..settings import get_client, get_settings
from . import tool


@tool(
    name="record_run_advice",
    description=(
        "Write a short self-evaluation of this chat turn to S3 under "
        "advice/raw/YYYY-MM-DD/ for later human curation. session_id is taken "
        "from server context (not a parameter). Call after non-trivial "
        "multi-tool sessions."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "session_summary": {"type": "string"},
            "what_worked": {"type": "string"},
            "improvement_ideas": {"type": "string"},
            "what_failed": {"type": "string", "default": ""},
            "athena_efficiency_score": {
                "type": "string",
                "enum": ["A", "B", "C", "D", "F", "N/A"],
                "default": "N/A",
            },
        },
        "required": ["session_summary", "what_worked", "improvement_ideas"],
    },
)
def record_run_advice(
    session_summary: str,
    what_worked: str,
    improvement_ideas: str,
    what_failed: str = "",
    athena_efficiency_score: str = "N/A",
) -> str:
    s = get_settings()
    bucket = s.output_bucket
    if not bucket:
        return "ERROR: OUTPUT_BUCKET not configured; cannot write advice."

    sid = session_id_ctx.get() or "unknown"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    day = ts[:10]
    prefix = (s.advice_prefix or "advice/raw").strip("/")
    key = f"{prefix}/{day}/session_{sid}__{ts}.md"

    model = s.bedrock_model_id
    body = f"""# Session {sid} - {ts}
**Athena efficiency:** {athena_efficiency_score}

## Summary
{session_summary}

## What worked
{what_worked}

## What failed
{what_failed or "(none)"}

## Improvement ideas
{improvement_ideas}

<!-- agent_version: env, model: {model} -->
"""
    raw = body.encode("utf-8")
    s3 = get_client("s3")
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=raw,
        ContentType="text/markdown; charset=utf-8",
    )
    uri = f"s3://{bucket}/{key}"
    return f"wrote {uri} ({len(raw) / 1024:.1f} KB)"
