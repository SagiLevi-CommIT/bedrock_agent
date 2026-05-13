"""Unit tests for Athena scan guard."""

from unittest.mock import MagicMock, patch

import pytest

from src.settings import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_run_athena_query_blocked_when_estimate_high(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATHENA_MAX_SCAN_GB_DEFAULT", "0.0000001")
    get_settings.cache_clear()
    from src.tools import athena as athena_mod

    with patch.object(athena_mod, "estimate_scan_for_sql") as est:
        est.return_value = {
            "estimate_bytes": 10**12,
            "estimate_cost_usd": 5.0,
            "partition_coverage": "partial",
            "target_table": "migrated_data.timeseries",
            "matched_partitions": 3,
            "notes": "",
        }
        out = athena_mod.run_athena_query(
            "SELECT 1 FROM migrated_data.timeseries WHERE date='2020-01-01'",
            confirm_heavy_scan=False,
        )
    assert "BLOCKED:" in out
    assert "confirm_heavy_scan=true" in out


def test_run_athena_query_runs_when_confirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATHENA_MAX_SCAN_GB_DEFAULT", "0.0000001")
    monkeypatch.setenv("ATHENA_RESULTS_BUCKET", "dummy-results")
    get_settings.cache_clear()
    from src.tools import athena as athena_mod

    with patch.object(athena_mod, "estimate_scan_for_sql") as est:
        est.return_value = {
            "estimate_bytes": 10**12,
            "estimate_cost_usd": 5.0,
            "partition_coverage": "partial",
            "target_table": "db.t",
            "matched_partitions": 1,
            "notes": "",
        }
        with patch.object(athena_mod, "athena_select_rows") as sel:
            sel.return_value = (
                "qid",
                100,
                [["c"], ["1"]],
            )
            out = athena_mod.run_athena_query(
                "SELECT 1 AS c FROM migrated_data.timeseries WHERE date='2020-01-01'",
                confirm_heavy_scan=True,
            )
    assert "BLOCKED" not in out
    assert "scanned_bytes=100" in out
    assert "query_id=qid" in out
