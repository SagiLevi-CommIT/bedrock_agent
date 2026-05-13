"""Tests for human byte formatting."""

from src.tools._helpers import human_bytes, scan_cost_usd


def test_human_bytes() -> None:
    assert "500 B" in human_bytes(500) or human_bytes(500) == "500 B"
    assert "KiB" in human_bytes(2048)


def test_scan_cost() -> None:
    # 1 TB at $5/TB = $5
    assert abs(scan_cost_usd(10**12, 5.0) - 5.0) < 0.001
