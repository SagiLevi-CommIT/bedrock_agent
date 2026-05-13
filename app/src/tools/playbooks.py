"""On-demand markdown playbooks baked into the image."""

from __future__ import annotations

import re
from pathlib import Path

from ..settings import get_settings
from . import tool


def _playbooks_root() -> Path:
    s = get_settings()
    p = Path(s.playbooks_dir)
    if p.is_dir():
        return p
    # Repo layout: knowledge/playbooks next to app/
    here = Path(__file__).resolve()
    for cand in (
        Path("/app/knowledge/playbooks"),
        here.parents[2] / "knowledge" / "playbooks",
        here.parents[3] / "knowledge" / "playbooks",
    ):
        if cand.is_dir():
            return cand
    return p


@tool(
    name="list_playbooks",
    description="List available playbook markdown files (name without .md).",
    input_schema={"type": "object", "properties": {}, "required": []},
)
def list_playbooks() -> str:
    root = _playbooks_root()
    if not root.is_dir():
        return f"ERROR: playbooks directory not found: {root}"
    lines: list[str] = []
    for f in sorted(root.glob("*.md")):
        name = f.stem
        subtitle = ""
        try:
            text = f.read_text(encoding="utf-8")
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("# "):
                    subtitle = line[2:].strip()
                    break
        except OSError:
            subtitle = "(unreadable)"
        lines.append(f"{name} -- {subtitle}")
    return "\n".join(lines) if lines else "(no playbooks)"


@tool(
    name="get_playbook",
    description=(
        "Return full markdown for a playbook by name (without .md). "
        "Special name 'session_lessons' reads the curated lessons file path "
        "from settings (live edits without rebuild when mounted)."
    ),
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
)
def get_playbook(name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "", name)
    if safe != name:
        return f"ERROR: invalid playbook name {name!r}"

    s = get_settings()
    if name == "session_lessons":
        path = Path(s.lessons_curated_path)
        if not path.is_file():
            return f"ERROR: curated lessons not found at {path}"
        return path.read_text(encoding="utf-8")

    f = _playbooks_root() / f"{name}.md"
    if not f.is_file():
        return f"ERROR: no playbook {name!r} under {_playbooks_root()}"
    return f.read_text(encoding="utf-8")
