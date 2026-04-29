"""FastAPI entry point. Phase 1 ships only /api/health.

Subsequent phases add /api/chat (Bedrock Converse loop), session storage, and
the ported tool registry.
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from pydantic import BaseModel

from .settings import get_settings

logger = logging.getLogger("agent")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="bedrock_agent", version="0.1.0")


class HealthResponse(BaseModel):
    status: str
    region: str
    model: str


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    s = get_settings()
    return HealthResponse(status="ok", region=s.aws_region, model=s.bedrock_model_id)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "bedrock_agent", "phase": "1-skeleton"}
