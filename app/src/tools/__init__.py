"""Tool registry. Each module under app.src.tools registers its callables here
via the @tool decorator. The Converse loop reads the registry to build the
toolConfig and to dispatch tool_use blocks.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

ToolFn = Callable[..., str]


@dataclass
class ToolEntry:
    name: str
    description: str
    input_schema: dict[str, Any]
    fn: ToolFn


REGISTRY: dict[str, ToolEntry] = {}


def tool(name: str, description: str, input_schema: dict[str, Any]) -> Callable[[ToolFn], ToolFn]:
    """Decorator to register a Python function as a Bedrock Converse tool."""

    def deco(fn: ToolFn) -> ToolFn:
        REGISTRY[name] = ToolEntry(
            name=name,
            description=description,
            input_schema=input_schema,
            fn=fn,
        )
        return fn

    return deco


def converse_tool_config() -> dict[str, Any]:
    """Convert the registry to the toolConfig parameter for bedrock-runtime Converse."""
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": e.name,
                    "description": e.description,
                    "inputSchema": {"json": e.input_schema},
                }
            }
            for e in REGISTRY.values()
        ]
    }


def call(name: str, args: dict[str, Any]) -> str:
    if name not in REGISTRY:
        return f"ERROR: unknown tool '{name}'. Available: {sorted(REGISTRY)}"
    try:
        return REGISTRY[name].fn(**args) or "(empty)"
    except TypeError as e:
        return f"ERROR: bad arguments for {name}: {e}"
    except Exception as e:  # noqa: BLE001 - tool errors must reach the model as text
        return f"ERROR: {name} failed: {type(e).__name__}: {e}"


def import_all() -> None:
    """Import every tool module so its @tool decorators run.

    Importing here keeps the registry assembly explicit; the chat handler
    calls this once at startup.
    """
    from . import athena, check_aws, glue, s3_explore  # noqa: F401
