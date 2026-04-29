"""FastAPI entry point for the hosted CardiacSense agent.

Routes:
  GET  /api/health   - liveness probe (no AWS calls)
  GET  /api/info     - service metadata + tool list
  POST /api/chat     - one chat turn against Bedrock Converse + the tool registry
  GET  /             - SPA index.html (and static assets) when ui_dist exists
  GET  /{any-spa-path} - SPA fallback to index.html
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .audit import configure_logging, log_event
from .converse_loop import converse
from .session_store import append_turn, load_history, new_session_id, next_turn_index
from .settings import get_settings
from .tools import REGISTRY, import_all

configure_logging(get_settings().log_level)
import_all()

app = FastAPI(title="bedrock_agent", version="0.2.0")


class HealthResponse(BaseModel):
    status: str
    region: str
    model: str
    tools: int


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    s = get_settings()
    return HealthResponse(
        status="ok", region=s.aws_region, model=s.bedrock_model_id, tools=len(REGISTRY)
    )


@app.get("/api/info")
def info() -> dict[str, Any]:
    return {
        "service": "bedrock_agent",
        "phase": "ui",
        "tools": sorted(REGISTRY.keys()),
    }


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    request_id: str
    text: str
    tool_trace: list[dict[str, Any]]
    usage: dict[str, int]
    iterations: int
    stop_reason: str
    latency_ms: int


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    request_id = uuid.uuid4().hex[:12]
    sid = req.session_id or new_session_id()
    turn = next_turn_index(sid)

    log_event(
        "agent.audit",
        "chat_request",
        request_id=request_id,
        session_id=sid,
        turn=turn,
        prompt_chars=len(req.prompt),
    )
    t0 = time.time()

    try:
        history = load_history(sid)
        user_msg = {"role": "user", "content": [{"text": req.prompt}]}
        history.append(user_msg)
        append_turn(sid, turn, "user", user_msg["content"])

        result = converse(history, request_id=request_id)

        # Persist every assistant + tool_result message produced this turn.
        for offset, msg in enumerate(result["messages"][turn + 1 :], start=1):
            append_turn(sid, turn + offset, msg["role"], msg["content"])
    except Exception as e:  # noqa: BLE001 - surface as 500 to client
        log_event(
            "agent.audit",
            "chat_error",
            request_id=request_id,
            session_id=sid,
            error=type(e).__name__,
            detail=str(e)[:500],
        )
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}") from e

    latency_ms = round((time.time() - t0) * 1000)
    log_event(
        "agent.cost",
        "chat_complete",
        request_id=request_id,
        session_id=sid,
        latency_ms=latency_ms,
        input_tokens=result["usage"]["input_tokens"],
        output_tokens=result["usage"]["output_tokens"],
        iterations=result["iterations"],
        stop_reason=result["stop_reason"],
        tools_called=len(result["tool_trace"]),
    )
    return ChatResponse(
        session_id=sid,
        request_id=request_id,
        text=result["text"],
        tool_trace=result["tool_trace"],
        usage=result["usage"],
        iterations=result["iterations"],
        stop_reason=result["stop_reason"],
        latency_ms=latency_ms,
    )


# --- Static SPA -------------------------------------------------------------
#
# The Dockerfile copies the built Vite bundle to /app/ui_dist. Locally we look
# under <repo>/ui/dist as a fallback so `uvicorn src.main:app --reload` after
# `cd ui && npm run build` also serves the UI.
#
# Mount must come AFTER all /api routes so they win on path matching. We also
# add a SPA-fallback handler so deep links / refreshes return index.html
# instead of 404.

_UI_DIR_CANDIDATES = [
    Path("/app/ui_dist"),
    Path(__file__).resolve().parents[2] / "ui" / "dist",
]
_UI_DIR = next((p for p in _UI_DIR_CANDIDATES if (p / "index.html").exists()), None)

if _UI_DIR is not None:
    log_event("agent.audit", "ui_mounted", path=str(_UI_DIR))
    _index = _UI_DIR / "index.html"

    app.mount(
        "/assets",
        StaticFiles(directory=str(_UI_DIR / "assets")),
        name="ui-assets",
    )

    @app.get("/")
    def spa_root() -> FileResponse:
        return FileResponse(_index)

    @app.get("/{path:path}")
    def spa_fallback(path: str) -> FileResponse:
        # Anything not handled by /api/* or /assets/* is the SPA.
        candidate = _UI_DIR / path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_index)
else:
    log_event(
        "agent.audit",
        "ui_missing",
        searched=[str(p) for p in _UI_DIR_CANDIDATES],
    )

    @app.get("/")
    def fallback_root() -> dict[str, Any]:
        return {
            "service": "bedrock_agent",
            "ui": "not built — run `npm run build` in ui/ or rebuild the container",
            "tools": sorted(REGISTRY.keys()),
        }
