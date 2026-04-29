"""DynamoDB-backed session store.

Schema:
  PK session_id (S), SK turn (N), ttl (N).
  Each item: {session_id, turn, role, content, created_at, ttl}.

`content` is the Bedrock Converse-shaped list of content blocks (text and/or
tool_use / tool_result), serialized as JSON-safe Python.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .settings import get_aws_session, get_settings

_SESSION_TTL_SECONDS = 7 * 24 * 3600


def _table():
    s = get_settings()
    ddb = get_aws_session().resource("dynamodb")
    return ddb.Table(s.sessions_table)


def new_session_id() -> str:
    return uuid.uuid4().hex


def load_history(session_id: str, limit: int = 30) -> list[dict[str, Any]]:
    """Return the conversation as a list of Bedrock Converse messages, oldest first."""
    resp = _table().query(
        KeyConditionExpression="session_id = :sid",
        ExpressionAttributeValues={":sid": session_id},
        ScanIndexForward=True,
        Limit=limit,
    )
    msgs: list[dict[str, Any]] = []
    for item in resp.get("Items", []):
        try:
            content = json.loads(item["content"])
        except (TypeError, ValueError):
            content = [{"text": str(item.get("content", ""))}]
        msgs.append({"role": item["role"], "content": content})
    return msgs


def append_turn(session_id: str, turn: int, role: str, content: list[dict[str, Any]]) -> None:
    now = int(time.time())
    _table().put_item(
        Item={
            "session_id": session_id,
            "turn": turn,
            "role": role,
            "content": json.dumps(content, default=str),
            "created_at": now,
            "ttl": now + _SESSION_TTL_SECONDS,
        }
    )


def next_turn_index(session_id: str) -> int:
    resp = _table().query(
        KeyConditionExpression="session_id = :sid",
        ExpressionAttributeValues={":sid": session_id},
        ScanIndexForward=False,
        Limit=1,
        ProjectionExpression="turn",
    )
    items = resp.get("Items", [])
    return int(items[0]["turn"]) + 1 if items else 0
