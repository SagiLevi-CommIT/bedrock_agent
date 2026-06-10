"""Unit tests for the agent-side Tool API wrappers + deterministic actions.

The httpx client (``call_tool_api``) is patched, so no network/AWS is touched.
Asserts the text the model sees and the clickable actions built from real
results (the LLM never invents URLs).
"""

from __future__ import annotations

from unittest.mock import patch

from src.tools import REGISTRY, data_tool
from src.tools.actions import collect_actions, reset_actions


def _patch_api(return_value=None, side_effect=None):
    return patch.object(data_tool, "call_tool_api", return_value=return_value, side_effect=side_effect)


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #


def test_tools_are_registered():
    for name in [
        "resolve_patient_context", "get_data_coverage", "check_data_availability",
        "summarize_available_files", "compare_sessions", "find_arrhythmia_events",
        "fetch_data", "generate_visualization", "submit_cardiolys_analysis",
        "get_job_status", "list_supported_cardiolys_types",
    ]:
        assert name in REGISTRY


# --------------------------------------------------------------------------- #
# inspect wrappers
# --------------------------------------------------------------------------- #


def test_resolve_patient_context():
    with _patch_api({"status": "ok", "patient_uuid": "925605c3-x", "provenance": "DB live"}):
        out = data_tool.resolve_patient_context(605)
    assert "925605c3-x" in out and "DB live" in out


def test_get_data_coverage_surfaces_strategy():
    payload = {
        "status": "ok", "strategy": "migrated", "provenance": "DB live",
        "files": 18, "segments": 2, "holes": 1,
        "validation": {"is_fully_covered": False},
        "coverage_report": "Covered 8h of 9h; 1 gap.",
    }
    with _patch_api(payload):
        out = data_tool.get_data_coverage(3525, "2026-06-09T22:00:00+03:00", "2026-06-10T07:00:00+03:00")
    assert "strategy=migrated" in out
    assert "provenance=DB live" in out
    assert "1 gap" in out


def test_check_data_availability_per_day():
    payload = {"status": "ok", "has_data": True, "total_files": 3, "strategy": "migrated",
               "days": [{"date": "2026-06-09", "files": 2}, {"date": "2026-06-10", "files": 1}]}
    with _patch_api(payload):
        out = data_tool.check_data_availability(3525, "a", "b")
    assert "has_data=True" in out and "2026-06-09:2" in out


def test_find_arrhythmia_events_lists_matches():
    payload = {"status": "ok", "count": 1, "matches": [
        {"patient_id": 739, "event_count": 12, "episode_count": 3,
         "file_key": "rearrangement/rt_flow/rt_flow_739_1.csv"}]}
    with _patch_api(payload):
        out = data_tool.find_arrhythmia_events("Atrial Fibrillation", "a", "b", patient_id=739)
    assert "1 matching file" in out and "events=12" in out


# --------------------------------------------------------------------------- #
# heavy jobs + actions
# --------------------------------------------------------------------------- #


def test_fetch_data_returns_job_id():
    with _patch_api({"status": "ok", "job_id": "job_abc", "job_status": "queued"}):
        out = data_tool.fetch_data(3525, "a", "b")
    assert "job_abc" in out and "get_job_status" in out


def test_generate_visualization_emits_no_premature_actions():
    # No /tool-ui web app exists this phase -- submitting a viz job must NOT
    # emit any button (the download button comes from get_job_status on success).
    reset_actions()
    with _patch_api({"status": "ok", "job_id": "job_viz", "job_status": "queued"}):
        out = data_tool.generate_visualization(3525, "2026-06-09T22:00:00+03:00",
                                               "2026-06-10T07:00:00+03:00", signal="respiratory")
    assert "job_viz" in out
    assert collect_actions() == []


def test_get_job_status_running():
    with _patch_api({"status": "running", "progress": {"message": "downloading"}}):
        out = data_tool.get_job_status("job_x")
    assert "status=running" in out and "downloading" in out


def test_get_job_status_succeeded_emits_actions():
    reset_actions()
    payload = {"status": "succeeded", "result": {"status": "ok", "artifacts": {
        "standalone_url": "https://signed/index_standalone.html",
        "standalone_note": None,
        "csv_urls": ["https://signed/a.csv"]}}}
    with _patch_api(payload):
        out = data_tool.get_job_status("job_x")
    assert "SUCCEEDED" in out
    acts = collect_actions()
    types = {a["type"] for a in acts}
    assert "download_standalone" in types
    assert "download_csv" in types
    viewer = next(a for a in acts if a["type"] == "download_standalone")
    assert viewer["url"] == "https://signed/index_standalone.html"


def test_get_job_status_oversized_standalone_surfaces_note():
    # Over the size cap the tool returns no link + a guidance note -- no button,
    # and the note must reach the model so it can steer the user.
    reset_actions()
    payload = {"status": "succeeded", "result": {"status": "ok", "artifacts": {
        "standalone_url": None,
        "standalone_note": "standalone viewer omitted (818 MB > 200 MB limit) -- "
                           "visualize a shorter time range for a downloadable viewer"}}}
    with _patch_api(payload):
        out = data_tool.get_job_status("job_x")
    assert "SUCCEEDED" in out and "shorter time range" in out
    assert collect_actions() == []


def test_get_job_status_failed():
    with _patch_api({"status": "failed", "error": "no overlap"}):
        out = data_tool.get_job_status("job_x")
    assert "FAILED" in out and "no overlap" in out


# --------------------------------------------------------------------------- #
# cardiolys consent gate
# --------------------------------------------------------------------------- #


def test_cardiolys_requires_confirmation():
    # No external call should happen without consent.
    with _patch_api({"should": "not be used"}) as m:
        out = data_tool.submit_cardiolys_analysis("rearrangement/rt_flow/rt_flow_739_1.csv")
    assert out.startswith("ERROR")
    m.assert_not_called()


def test_cardiolys_submits_with_consent():
    with _patch_api({"status": "ok", "job_id": "job_card"}):
        out = data_tool.submit_cardiolys_analysis(
            "rearrangement/rt_flow/rt_flow_739_1740825889000.csv", confirm_external=True)
    assert "job_card" in out
