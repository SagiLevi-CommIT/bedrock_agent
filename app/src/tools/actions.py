"""Request-scoped collector for deterministic UI actions (clickable buttons/links).

The wrapper tools append structured actions built from REAL tool-API results
(artifact links, deep links). The LLM never fabricates a URL -- it only writes
prose; the buttons come from here. The chat handler resets the collector at the
start of each turn and returns whatever was collected in ``ChatResponse.actions``.

An action is ``{type, label, url, **extra}`` where ``type`` is one of
``download_standalone`` / ``download_csv`` / ``open_cardiolys_raw`` /
``open_report_pdf``. (``open_visualization`` / ``open_tool_ui`` are reserved for
the future hosted viewer and ``/tool-ui`` web app -- neither exists this phase.)
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_actions_ctx: ContextVar[list[dict[str, Any]] | None] = ContextVar("agent_actions", default=None)


def reset_actions() -> None:
    """Begin a fresh collection (call once per chat turn)."""
    _actions_ctx.set([])


def add_action(action_type: str, label: str, url: str, **extra: Any) -> None:
    """Record one deterministic action derived from a real tool result.

    Buttons are always presigned https links from real tool results. Reject any
    other scheme defensively, so a bad value can never reach the UI as a button
    that navigates the SPA away (the s3://-link footgun lived in model prose, but
    keep the action channel clean too).
    """
    if not url.startswith("https://"):
        raise ValueError(f"action URL must be an https:// link; got {url!r}")
    actions = _actions_ctx.get()
    if actions is None:
        actions = []
        _actions_ctx.set(actions)
    actions.append({"type": action_type, "label": label, "url": url, **extra})


def collect_actions() -> list[dict[str, Any]]:
    """Return a copy of the actions collected this turn."""
    return list(_actions_ctx.get() or [])
