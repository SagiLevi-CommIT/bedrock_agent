"""Agent-facing wrappers around the deterministic Tool API (the S3
data/visualization tool). These are thin httpx clients -- all business logic
(S3/Athena access, coverage math, fetching, visualization, Cardiolys) lives in
the tool, behind a stable contract. The agent only orchestrates and explains.

Tiering (do not blur):
  * INSPECT tools (resolve/coverage/availability/summarize/list/events) are
    metadata-only -- they never download data.
  * FETCH / VISUALIZE / CARDIOLYS submit async jobs that run server-side and
    publish artifacts to S3; the user gets links (poll with get_job_status).
    Never call fetch_data as a side effect of an availability/coverage question.

Clickable buttons (download standalone viewer, download CSV, raw Cardiolys
JSON) are emitted deterministically from real tool results via tools.actions --
the model must NOT invent URLs.
"""

from __future__ import annotations

from typing import Any

from . import tool
from .actions import add_action
from .tool_api_client import call_tool_api

_FLOW = {
    "type": "string",
    "enum": ["sleep_flow", "rt_flow"],
    "default": "sleep_flow",
    "description": "sleep_flow (continuous) or rt_flow (event-based).",
}
_RANGE_PROPS = {
    "patient_id": {"type": "integer", "description": "Bare integer patient id."},
    "flow": _FLOW,
    "start": {"type": "string", "description": "ISO-8601 start (include an offset for an exact instant)."},
    "end": {"type": "string", "description": "ISO-8601 end."},
}
_RANGE_REQUIRED = ["patient_id", "start", "end"]


# --------------------------------------------------------------------------- #
# Inspect (sync, metadata-only)
# --------------------------------------------------------------------------- #


@tool(
    name="resolve_patient_context",
    description=(
        "Resolve an integer patient_id to its canonical UUID via the deterministic "
        "tool (cache -> Postgres -> HTTP resolver), with provenance. Mapping is "
        "DB/tool-driven -- never invent a UUID."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "patient_id": {"type": "integer", "description": "Bare integer patient id."},
            "force_refresh": {"type": "boolean", "default": False},
        },
        "required": ["patient_id"],
    },
)
def resolve_patient_context(patient_id: int, force_refresh: bool = False) -> str:
    d = call_tool_api("POST", "/v1/resolve-patient",
                      json_body={"patient_id": int(patient_id), "force_refresh": force_refresh})
    return f"patient_id={patient_id} -> pUuid={d['patient_uuid']} (provenance: {d['provenance']})"


@tool(
    name="get_data_coverage",
    description=(
        "Coverage / missing-data for a patient+flow over a time range, via the "
        "deterministic tool's migrated-data discovery (probe-free when available; "
        "S3 metadata only -- no downloads). Use for 'do we have data', 'any gaps', "
        "'is it complete'. Returns the coverage report + which discovery strategy "
        "and patient-mapping provenance were used."
    ),
    input_schema={"type": "object", "properties": dict(_RANGE_PROPS), "required": _RANGE_REQUIRED},
)
def get_data_coverage(patient_id: int, start: str, end: str, flow: str = "sleep_flow") -> str:
    d = call_tool_api("POST", "/v1/discover",
                      json_body={"patient_id": int(patient_id), "flow": flow, "start": start, "end": end})
    v = d.get("validation", {})
    return (
        f"coverage for patient {patient_id} {flow} {start}..{end} "
        f"[strategy={d.get('strategy')}, provenance={d.get('provenance')}]\n"
        f"files={d.get('files')}, segments={d.get('segments')}, gaps={d.get('holes')}, "
        f"fully_covered={v.get('is_fully_covered')}\n{d.get('coverage_report', '')}"
    )


@tool(
    name="check_data_availability",
    description=(
        "Fast 'does data exist, and on which days' for a patient+flow over a range "
        "(one migrated-data query, no downloads). Use before deciding to fetch or "
        "visualize. Returns per-day file counts."
    ),
    input_schema={"type": "object", "properties": dict(_RANGE_PROPS), "required": _RANGE_REQUIRED},
)
def check_data_availability(patient_id: int, start: str, end: str, flow: str = "sleep_flow") -> str:
    d = call_tool_api("POST", "/v1/availability",
                      json_body={"patient_id": int(patient_id), "flow": flow, "start": start, "end": end})
    days = ", ".join(f"{x['date']}:{x['files']}" for x in d.get("days", [])) or "(none)"
    return (
        f"availability patient {patient_id} {flow}: has_data={d.get('has_data')}, "
        f"total_files={d.get('total_files')} [strategy={d.get('strategy')}]\nper-day: {days}"
    )


@tool(
    name="summarize_available_files",
    description=(
        "Data-quality summary for a patient+flow+range: file count, per-day spread, "
        "coverage completeness, gap count (metadata only, no downloads)."
    ),
    input_schema={"type": "object", "properties": dict(_RANGE_PROPS), "required": _RANGE_REQUIRED},
)
def summarize_available_files(patient_id: int, start: str, end: str, flow: str = "sleep_flow") -> str:
    d = call_tool_api("POST", "/v1/summarize-files",
                      json_body={"patient_id": int(patient_id), "flow": flow, "start": start, "end": end})
    return (
        f"summary patient {patient_id} {flow}: total_files={d.get('total_files')}, "
        f"segments={d.get('segments')}, gaps={d.get('gap_count')}, "
        f"fully_covered={d.get('is_fully_covered')} [strategy={d.get('strategy')}]"
    )


@tool(
    name="compare_sessions",
    description=(
        "Compare coverage of range A vs range B for one patient+flow "
        "(e.g. 'last night vs the night before'). Metadata only, no downloads."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "patient_id": {"type": "integer"},
            "flow": _FLOW,
            "a_start": {"type": "string", "description": "Range A start (ISO-8601)."},
            "a_end": {"type": "string"},
            "b_start": {"type": "string", "description": "Range B start (ISO-8601)."},
            "b_end": {"type": "string"},
        },
        "required": ["patient_id", "a_start", "a_end", "b_start", "b_end"],
    },
)
def compare_sessions(patient_id: int, a_start: str, a_end: str, b_start: str, b_end: str,
                     flow: str = "sleep_flow") -> str:
    d = call_tool_api("POST", "/v1/compare", json_body={
        "patient_id": int(patient_id), "flow": flow,
        "a_start": a_start, "a_end": a_end, "b_start": b_start, "b_end": b_end,
    })
    return f"compare patient {patient_id} {flow}: {d.get('summary')}"


@tool(
    name="find_arrhythmia_events",
    description=(
        "Search for arrhythmia events (e.g. Atrial Fibrillation) across rt_flow "
        "files in a range; returns matching files with event/episode counts. Use "
        "list_arrhythmia_labels first if unsure of the exact label."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "arrhythmia": {"type": "string", "description": "Arrhythmia label."},
            "start": {"type": "string"},
            "end": {"type": "string"},
            "patient_id": {"type": "integer", "description": "Optional: restrict to one patient."},
            "min_count": {"type": "integer", "default": 1, "minimum": 1},
        },
        "required": ["arrhythmia", "start", "end"],
    },
)
def find_arrhythmia_events(arrhythmia: str, start: str, end: str,
                           patient_id: int | None = None, min_count: int = 1) -> str:
    body: dict[str, Any] = {"arrhythmia": arrhythmia, "start": start, "end": end, "min_count": int(min_count)}
    if patient_id is not None:
        body["patient_id"] = int(patient_id)
    d = call_tool_api("POST", "/v1/search-events", json_body=body)
    lines = [
        f"  {m['patient_id']}  events={m['event_count']} episodes={m['episode_count']}  {m['file_key']}"
        for m in d.get("matches", [])[:25]
    ]
    return f"{d.get('count', 0)} matching file(s) for {arrhythmia!r}:\n" + ("\n".join(lines) or "  (none)")


@tool(
    name="list_supported_cardiolys_types",
    description="List what the Cardiolys analysis can report (beat legend + known rhythm-event types).",
    input_schema={"type": "object", "properties": {}},
)
def list_supported_cardiolys_types() -> str:
    d = call_tool_api("GET", "/v1/cardiolys/supported-types")
    return (
        f"known rhythm-event types: {d.get('known_rhythm_event_types')}; "
        f"beat annotations: {d.get('beat_annotations')}. {d.get('note', '')}"
    )


# --------------------------------------------------------------------------- #
# Heavy ops (async jobs -> artifacts/links). Poll with get_job_status.
# --------------------------------------------------------------------------- #


@tool(
    name="fetch_data",
    description=(
        "Start a server-side DOWNLOAD job (merge to CSV) for a patient+flow+range. "
        "ONLY use when the user explicitly asks to download/export data -- never to "
        "answer an availability/coverage question. Returns a job_id; poll "
        "get_job_status for the presigned download link. Nothing downloads to the user."
    ),
    input_schema={
        "type": "object",
        "properties": {
            **_RANGE_PROPS,
            "mode": {"type": "string", "enum": ["processed", "raw"], "default": "processed"},
        },
        "required": _RANGE_REQUIRED,
    },
)
def fetch_data(patient_id: int, start: str, end: str, flow: str = "sleep_flow",
               mode: str = "processed") -> str:
    d = call_tool_api("POST", "/v1/jobs", json_body={
        "type": "fetch", "patient_id": int(patient_id), "flow": flow,
        "start": start, "end": end, "mode": mode,
    })
    return f"download job started: job_id={d['job_id']}. Poll get_job_status({d['job_id']}) for the link."


@tool(
    name="generate_visualization",
    description=(
        "Start a server-side VISUALIZATION job (sleep_flow): fetch + build the "
        "self-contained signal viewer (single HTML file) in the cloud. Returns a "
        "job_id; poll get_job_status for the presigned viewer download link. "
        "No files download to the user unless they click."
    ),
    input_schema={
        "type": "object",
        "properties": {**_RANGE_PROPS, "signal": {"type": "string", "description": "Optional signal of interest (e.g. respiratory)."}},
        "required": _RANGE_REQUIRED,
    },
)
def generate_visualization(patient_id: int, start: str, end: str, flow: str = "sleep_flow",
                           signal: str | None = None) -> str:
    d = call_tool_api("POST", "/v1/jobs", json_body={
        "type": "fetch_and_visualize", "patient_id": int(patient_id), "flow": flow,
        "start": start, "end": end,
    })
    return (
        f"visualization job started: job_id={d['job_id']}. "
        f"Poll get_job_status({d['job_id']}) for the viewer download link."
    )


@tool(
    name="submit_cardiolys_analysis",
    description=(
        "Submit ONE rt_flow recording's ECG to the EXTERNAL Cardiolys service for "
        "arrhythmia analysis. This sends patient ECG outside CardiacSense -- only "
        "call after the user has explicitly confirmed; set confirm_external=true. "
        "Returns a job_id; poll get_job_status for the result. Present results with "
        "strict provenance: what Cardiolys returned vs what the tool computed."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_key": {"type": "string", "description": "rt_flow S3 key to analyze."},
            "confirm_external": {
                "type": "boolean",
                "default": False,
                "description": "Must be true; the user has confirmed sending ECG externally.",
            },
        },
        "required": ["file_key", "confirm_external"],
    },
)
def submit_cardiolys_analysis(file_key: str, confirm_external: bool = False) -> str:
    if not confirm_external:
        return (
            "ERROR: external send not confirmed. Ask the user to confirm sending this "
            "recording's ECG to the external Cardiolys service, then call again with "
            "confirm_external=true."
        )
    d = call_tool_api("POST", "/v1/cardiolys/analyze",
                      json_body={"file_key": file_key, "confirm_external": True})
    return f"Cardiolys analysis job started: job_id={d['job_id']}. Poll get_job_status({d['job_id']})."


@tool(
    name="get_job_status",
    description=(
        "Poll a job (fetch / visualization / Cardiolys). When succeeded, returns "
        "the result and emits clickable buttons for any artifacts (standalone "
        "viewer download, CSV download, raw Cardiolys JSON). Call repeatedly "
        "until status is 'succeeded' or 'failed'."
    ),
    input_schema={
        "type": "object",
        "properties": {"job_id": {"type": "string"}},
        "required": ["job_id"],
    },
)
def get_job_status(job_id: str) -> str:
    d = call_tool_api("GET", f"/v1/jobs/{job_id}")
    status = d.get("status")
    if status != "succeeded":
        prog = (d.get("progress") or {}).get("message")
        tail = f" ({prog})" if prog else ""
        if status == "failed":
            return f"job {job_id} FAILED: {d.get('error')}"
        return f"job {job_id} status={status}{tail}. Poll again shortly."

    result = d.get("result") or {}
    rstatus = result.get("status")
    if rstatus and rstatus != "ok":
        return f"job {job_id} finished with {rstatus}: {result.get('error')}"

    art = result.get("artifacts") or {}
    notes: list[str] = []
    if art.get("standalone_url"):
        add_action("download_standalone", "Download viewer (HTML)", art["standalone_url"])
        notes.append("viewer ready")
    if art.get("standalone_note"):
        notes.append(art["standalone_note"])
    for i, url in enumerate(art.get("csv_urls") or [], start=1):
        add_action("download_csv", f"Download CSV {i}", url)
        notes.append("csv ready")
    # Cardiolys result: surface raw link + the provenance-separated summary.
    if result.get("raw_json_url"):
        add_action("open_cardiolys_raw", "Open raw Cardiolys JSON", result["raw_json_url"])
    if "summary" in result:
        notes.append(f"Cardiolys(tool-computed)={result['summary']}; vendor_raw={result.get('raw_excerpt')}")
    if result.get("coverage_report"):
        notes.append("coverage report attached")
    return f"job {job_id} SUCCEEDED. " + ("; ".join(notes) if notes else "done")
