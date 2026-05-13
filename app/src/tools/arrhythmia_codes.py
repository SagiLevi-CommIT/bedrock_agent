"""Cardiolyse / rhythm annotation labels for search and SQL filters."""

from __future__ import annotations

from . import tool

# Display name -> canonical values used in migrated_data.pc_timeseries `` `crlyse-annotation` ``
# and common synonyms (AF, AFIB, etc.).
_ARRHYTHMIA_ENTRIES: list[tuple[str, list[str], list[str]]] = [
    ("Atrial Fibrillation", ["ATRIAL_FIBRILLATION", "AF", "AFIB", "A_FIB"], ["1021"]),
    ("Atrial Flutter", ["ATRIAL_FLUTTER", "AFL"], []),
    ("Premature Ventricular Contraction", ["PVC", "VPC", "VENTRICULAR_EXTRASYSTOLE"], []),
    ("Ventricular Tachycardia", ["VT", "VENTRICULAR_TACHYCARDIA"], []),
    ("Supraventricular Tachycardia", ["SVT"], []),
    ("Bradycardia", ["BRADYCARDIA", "SINUS_BRADYCARDIA"], []),
    ("Pause / Asystole", ["PAUSE", "ASYSTOLE"], []),
    ("Noise / Unreadable", ["NOISE", "UNREADABLE", "ARTIFACT"], []),
    ("Normal Sinus Rhythm", ["NSR", "NORMAL"], []),
]


def annotation_sql_in_clause(label_query: str) -> tuple[str, str] | None:
    """Return (description, SQL IN list fragment) for a fuzzy label match."""
    q = label_query.strip().lower()
    for display, keys, _codes in _ARRHYTHMIA_ENTRIES:
        if q == display.lower():
            vals = ", ".join(f"'{k}'" for k in keys)
            return display, vals
        for k in keys:
            if q == k.lower():
                vals = ", ".join(f"'{x}'" for x in keys)
                return display, vals
    return None


@tool(
    name="list_arrhythmia_labels",
    description=(
        "List supported arrhythmia / rhythm labels for "
        "search_files_with_arrhythmia_events. Each line: display name, "
        "annotation keys, optional reference codes."
    ),
    input_schema={"type": "object", "properties": {}, "required": []},
)
def list_arrhythmia_labels() -> str:
    lines: list[str] = []
    for display, keys, codes in _ARRHYTHMIA_ENTRIES:
        ck = f"  codes={codes}" if codes else ""
        lines.append(f"{display}  keys={keys}{ck}")
    return "\n".join(lines)
