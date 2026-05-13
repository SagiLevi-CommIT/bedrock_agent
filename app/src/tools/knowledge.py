"""Knowledge / skill loader tools.

Lets the model pull a single skill or knowledge file into context on demand
instead of bloating the system prompt. Files live under
`/app/skills/` and `/app/knowledge/` in the container, or
`<repo>/skills/` and `<repo>/knowledge/` in local dev.
"""
from __future__ import annotations

from pathlib import Path

from . import tool

_SKILLS_CANDIDATES = [
    Path("/app/skills"),
    Path(__file__).resolve().parents[3] / "skills",
]
_KNOWLEDGE_CANDIDATES = [
    Path("/app/knowledge"),
    Path(__file__).resolve().parents[3] / "knowledge",
]


def _resolve(candidates: list[Path]) -> Path | None:
    for p in candidates:
        if p.is_dir():
            return p
    return None


def _safe_read(root: Path, name: str, allowed_suffixes: tuple[str, ...]) -> str:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return f"ERROR: invalid name {name!r}; must be a bare filename without path separators"
    target = root / name
    if not target.is_file():
        sib = sorted(p.name for p in root.iterdir() if p.is_file() and p.suffix in allowed_suffixes)
        return f"ERROR: {name!r} not found under {root}. Available: {sib}"
    if target.suffix not in allowed_suffixes:
        return f"ERROR: {target.suffix!r} not allowed; supported suffixes: {allowed_suffixes}"
    return target.read_text(encoding="utf-8")


@tool(
    name="list_skills",
    description=(
        "List the available domain-knowledge skill files. Each skill is a focused, "
        "procedural recipe (e.g. 'rearrangement_skill', 'sleep_skill', "
        "'athena_cost_rules', 'limitations'). Returns each skill's name + the "
        "one-line description from its 'description:' header. Always call this "
        "before constructing a query about REARRENGEMENT, POST_COMPUTATION, or "
        "any flow specifics — then load the matching skill with read_skill."
    ),
    input_schema={"type": "object", "properties": {}, "required": []},
)
def list_skills() -> str:
    root = _resolve(_SKILLS_CANDIDATES)
    if root is None:
        return f"ERROR: skills directory not found. Searched: {[str(p) for p in _SKILLS_CANDIDATES]}"
    lines = [f"Skills under {root}:"]
    for p in sorted(root.glob("*.yaml")):
        # Read the first 'description:' line cheaply
        desc = ""
        for raw in p.read_text(encoding="utf-8").splitlines()[:5]:
            stripped = raw.strip()
            if stripped.startswith("description:"):
                desc = stripped[len("description:") :].strip()
                break
        lines.append(f"  - {p.stem}: {desc}")
    return "\n".join(lines)


@tool(
    name="read_skill",
    description=(
        "Load the full contents of a skill YAML by name (without the .yaml "
        "suffix). Use this after list_skills to pull a specific skill into "
        "context. Examples: read_skill(name='naming_conventions'), "
        "read_skill(name='post_computation_skill')."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name without .yaml suffix"},
        },
        "required": ["name"],
    },
)
def read_skill(name: str) -> str:
    root = _resolve(_SKILLS_CANDIDATES)
    if root is None:
        return f"ERROR: skills directory not found. Searched: {[str(p) for p in _SKILLS_CANDIDATES]}"
    filename = name if name.endswith(".yaml") else f"{name}.yaml"
    return _safe_read(root, filename, allowed_suffixes=(".yaml",))


@tool(
    name="read_knowledge",
    description=(
        "Read a single file from the knowledge directory by filename (e.g. "
        "'pipeline_lineage.md', 'schemas.md', 'caveats.md', 'naming_conventions.md', "
        "'flow_decision_tree.md', 'column_profiles.md', 'dataset_families.json', "
        "'s3_catalog.json'). Use this for in-depth reference — skills are the "
        "preferred procedural source."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Full filename including extension, e.g. 'pipeline_lineage.md'",
            },
        },
        "required": ["filename"],
    },
)
def read_knowledge(filename: str) -> str:
    root = _resolve(_KNOWLEDGE_CANDIDATES)
    if root is None:
        return f"ERROR: knowledge directory not found. Searched: {[str(p) for p in _KNOWLEDGE_CANDIDATES]}"
    return _safe_read(root, filename, allowed_suffixes=(".md", ".json", ".yaml"))
