"""Registry contains all Converse tools after import_all."""

from src.tools import REGISTRY, converse_tool_config, import_all


def test_registry_loaded() -> None:
    import_all()
    expected = {
        "check_aws_connection",
        "list_databases",
        "list_tables",
        "describe_table",
        "search_tables",
        "run_athena_query",
        "estimate_athena_scan",
        "explore_s3",
        "presign_s3_object",
        "list_skills",
        "read_skill",
        "read_knowledge",
        "resolve_patient_uuid",
        "latest_data_date_for_patient",
        "parse_app_events_key",
        "list_patient_files",
        "find_patient_last_upload",
        "patient_usage_summary",
        "merge_patient_window",
        "list_arrhythmia_labels",
        "search_files_with_arrhythmia_events",
        "probe_file_time_range",
        "probe_files_batch",
        "find_rt_flow_files_in_window",
        "coverage_report_from_athena",
        "record_run_advice",
        "list_playbooks",
        "get_playbook",
        # Deterministic data-tool wrappers (tools/data_tool.py)
        "resolve_patient_context",
        "get_data_coverage",
        "check_data_availability",
        "summarize_available_files",
        "compare_sessions",
        "find_arrhythmia_events",
        "list_supported_cardiolys_types",
        "fetch_data",
        "generate_visualization",
        "visualize_rt_file",
        "patient_timeline",
        "resolve_uuid_to_patient_id",
        "get_patient_report",
        "request_report_restore",
        "submit_cardiolys_analysis",
        "get_job_status",
    }
    assert expected == set(REGISTRY.keys())


def test_tool_config_shape() -> None:
    import_all()
    cfg = converse_tool_config()
    assert "tools" in cfg
    for spec in cfg["tools"]:
        ts = spec["toolSpec"]
        assert ts["name"]
        assert ts["description"]
        assert ts["inputSchema"]["json"]["type"] == "object"
