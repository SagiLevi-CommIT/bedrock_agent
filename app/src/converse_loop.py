"""Bedrock Converse + tool-use loop.

Keeps the agent loop hand-rolled (no Strands SDK). Each turn:
  1. Send {system, messages, toolConfig} to bedrock-runtime:Converse.
  2. If response has stopReason='tool_use', dispatch every tool_use block in
     the registry, build the tool_result content, append to messages, repeat.
  3. Otherwise, return the assistant's text + the full tool trace + token usage.

Iteration cap is hard-coded to 10 to prevent runaway loops.
"""
from __future__ import annotations

import logging
from typing import Any

from .audit import log_event
from .session_context import session_id_ctx
from .settings import get_client, get_settings
from .tools import call as call_tool
from .tools import converse_tool_config

logger = logging.getLogger("agent.bedrock")

MAX_ITERS = 20


def _read_system_prompt() -> str:
    """Read the system prompt, trying multiple known locations."""
    from pathlib import Path

    candidates = [
        Path("/app/prompts/system_prompt.md"),
        Path(__file__).resolve().parents[1] / "prompts" / "system_prompt.md",
        Path(__file__).resolve().parents[2] / "prompts" / "system_prompt.md",
        Path.cwd() / "prompts" / "system_prompt.md",
    ]
    for p in candidates:
        try:
            return p.read_text(encoding="utf-8")
        except (FileNotFoundError, NotADirectoryError):
            continue
    # Diagnostic: dump what's actually present so we can see why all paths failed.
    diag: list[str] = []
    for d in [Path("/app"), Path("/app/prompts"), Path.cwd()]:
        try:
            diag.append(f"{d}: {sorted(p.name for p in d.iterdir())[:20]}")
        except Exception as e:
            diag.append(f"{d}: <{type(e).__name__}: {e}>")
    raise FileNotFoundError(
        f"system_prompt.md not found in any of: {[str(p) for p in candidates]}. "
        f"Diagnostics: {diag}"
    )


def converse(
    messages: list[dict[str, Any]],
    system_prompt: str | None = None,
    request_id: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    """Run the full Bedrock Converse loop until the model stops or hits MAX_ITERS.

    Args:
        messages: list of {role, content[]} entries; the latest user turn must
            already be appended.
        system_prompt: override the on-disk prompt (mainly for tests).
        request_id: opaque trace id for logs.
        session_id: chat session id for tools that write context (e.g. advice).

    Returns:
        dict with: text (final assistant message), messages (updated history),
        tool_trace (list of {name, args, result, latency_ms}), usage
        (input/output tokens summed across iterations), stop_reason.
    """
    s = get_settings()
    bedrock = get_client("bedrock-runtime")
    sys_text = system_prompt if system_prompt is not None else _read_system_prompt()
    tool_config = converse_tool_config()

    token = session_id_ctx.set(session_id or "")
    try:
        return _converse_inner(
            messages=messages,
            request_id=request_id,
            s=s,
            bedrock=bedrock,
            sys_text=sys_text,
            tool_config=tool_config,
        )
    finally:
        session_id_ctx.reset(token)


def _converse_inner(
    *,
    messages: list[dict[str, Any]],
    request_id: str,
    s: Any,
    bedrock: Any,
    sys_text: str,
    tool_config: dict[str, Any],
) -> dict[str, Any]:
    tool_trace: list[dict[str, Any]] = []
    total_in = 0
    total_out = 0

    for i in range(MAX_ITERS):
        kwargs: dict[str, Any] = {
            "modelId": s.bedrock_model_id,
            "messages": messages,
            "system": [{"text": sys_text}],
            "inferenceConfig": {"maxTokens": s.bedrock_max_tokens, "temperature": 0.2},
        }
        if tool_config["tools"]:
            kwargs["toolConfig"] = tool_config

        log_event(
            "agent.bedrock",
            "converse_request",
            iter=i,
            request_id=request_id,
            messages=len(messages),
            tools=len(tool_config["tools"]),
        )
        resp = bedrock.converse(**kwargs)
        usage = resp.get("usage", {})
        total_in += int(usage.get("inputTokens", 0))
        total_out += int(usage.get("outputTokens", 0))

        out = resp["output"]["message"]
        messages.append(out)

        stop_reason = resp.get("stopReason", "end_turn")
        if stop_reason != "tool_use":
            text_parts = [b["text"] for b in out["content"] if "text" in b]
            return {
                "text": "\n".join(text_parts).strip(),
                "messages": messages,
                "tool_trace": tool_trace,
                "usage": {"input_tokens": total_in, "output_tokens": total_out},
                "stop_reason": stop_reason,
                "iterations": i + 1,
            }

        # Run every tool_use block in this turn
        tool_results: list[dict[str, Any]] = []
        for block in out["content"]:
            if "toolUse" not in block:
                continue
            tu = block["toolUse"]
            name = tu["name"]
            args = tu.get("input", {}) or {}
            tool_id = tu["toolUseId"]
            import time

            t0 = time.time()
            result = call_tool(name, args)
            latency = round((time.time() - t0) * 1000)
            tool_trace.append(
                {"name": name, "args": args, "result": result[:1000], "latency_ms": latency}
            )
            log_event(
                "agent.tool_trace",
                "tool_call",
                name=name,
                latency_ms=latency,
                request_id=request_id,
                ok=not result.startswith("ERROR"),
            )
            tool_results.append(
                {"toolResult": {"toolUseId": tool_id, "content": [{"text": result}]}}
            )
        messages.append({"role": "user", "content": tool_results})

    return {
        "text": "(stopped: max tool iterations reached)",
        "messages": messages,
        "tool_trace": tool_trace,
        "usage": {"input_tokens": total_in, "output_tokens": total_out},
        "stop_reason": "max_iters",
        "iterations": MAX_ITERS,
    }
