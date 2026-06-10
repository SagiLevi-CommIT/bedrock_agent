"""Thin httpx client for the deterministic Tool API (``/tool-api/v1``).

Mirrors patient_resolver.py: bearer token from a direct setting/env (local) or
Secrets Manager (prod), short timeout, JSON in/out. Raises :class:`ToolApiError`
on a non-2xx response; the calling @tool functions let the registry turn that
into an ``ERROR: ...`` string for the model.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..settings import get_client, get_settings

_TOKEN_CACHE: dict[str, str] = {}


class ToolApiError(RuntimeError):
    """A tool-api call failed (transport, non-2xx, or bad payload)."""


def _base_url() -> str:
    url = get_settings().tool_api_base_url or os.environ.get("TOOL_API_BASE_URL")
    if not url:
        raise ToolApiError(
            "TOOL_API_BASE_URL is not configured -- the agent cannot reach the data tool."
        )
    return url.rstrip("/")


def _token() -> str | None:
    s = get_settings()
    if s.tool_api_token:
        return s.tool_api_token
    env = os.environ.get("TOOL_API_TOKEN")
    if env:
        return env
    secret_name = s.tool_api_token_secret_name or os.environ.get("TOOL_API_TOKEN_SECRET_NAME")
    if not secret_name:
        return None  # auth disabled on the tool side (dev)
    if secret_name in _TOKEN_CACHE:
        return _TOKEN_CACHE[secret_name]
    raw = (get_client("secretsmanager").get_secret_value(SecretId=secret_name).get("SecretString") or "").strip()
    value = raw
    if raw.startswith("{"):
        try:
            d = json.loads(raw)
            value = d.get("TOOL_API_TOKEN") or d.get("token") or raw
        except json.JSONDecodeError:
            value = raw
    _TOKEN_CACHE[secret_name] = value
    return value


def call_tool_api(method: str, path: str, *, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call the tool-api and return the parsed JSON object. Raises ToolApiError."""
    import httpx

    headers = {"Accept": "application/json"}
    tok = _token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    url = f"{_base_url()}{path}"
    try:
        with httpx.Client(timeout=float(get_settings().tool_api_timeout_s)) as c:
            resp = c.request(method, url, json=json_body, headers=headers)
    except httpx.HTTPError as e:
        raise ToolApiError(f"tool-api {method} {path} unreachable: {type(e).__name__}: {e}") from e
    if resp.status_code >= 400:
        raise ToolApiError(f"tool-api {method} {path} -> HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        return resp.json()
    except ValueError as e:
        raise ToolApiError(f"tool-api {path} returned non-JSON: {resp.text[:200]}") from e
