"""Request-scoped context for tools (e.g. session_id for advice writes)."""

from __future__ import annotations

from contextvars import ContextVar

session_id_ctx: ContextVar[str] = ContextVar("agent_session_id", default="")
