"""Gap detection, coverage validation, and reporting.

Provides:
- ``detect_gaps`` -- find discontinuities in sorted timestamps
- ``validate_time_coverage`` -- explicit check: does the actual data fully
  cover the requested window?
- ``build_coverage_report`` -- human-readable report with partial-coverage
  diagnostics, missing-tail detection, and next-file hints
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from .config import FlowConfig

logger = logging.getLogger(__name__)


@dataclass
class GapInfo:
    gap_start: datetime
    gap_end: datetime
    duration: timedelta


@dataclass
class CoverageValidation:
    """Result of :func:`validate_time_coverage`."""

    requested_start: datetime
    requested_end: datetime
    actual_start: datetime | None
    actual_end: datetime | None
    is_fully_covered: bool
    missing_head: timedelta | None = None
    missing_tail: timedelta | None = None
    gaps: list[GapInfo] | None = None
    next_file_start: datetime | None = None


def detect_gaps(
    timestamps: pd.Series,
    config: FlowConfig,
) -> list[GapInfo]:
    """Detect discontinuities where the interval between consecutive
    samples exceeds ``estimated_chunk_duration * gap_threshold_multiplier``.

    *timestamps* must be a sorted ``datetime64[ns, UTC]`` Series.
    """
    if len(timestamps) < 2:
        return []

    threshold = timedelta(
        minutes=config.estimated_chunk_duration_min * config.gap_threshold_multiplier
    )

    diffs = timestamps.diff()
    gap_mask = diffs > threshold

    gaps: list[GapInfo] = []
    gap_indices = timestamps.index[gap_mask]

    for idx in gap_indices:
        loc = timestamps.index.get_loc(idx)
        prev_idx = timestamps.index[loc - 1]
        gap_start = timestamps[prev_idx]
        gap_end = timestamps[idx]
        gaps.append(GapInfo(
            gap_start=gap_start.to_pydatetime(),
            gap_end=gap_end.to_pydatetime(),
            duration=gap_end - gap_start,
        ))

    logger.info("Detected %d gaps (threshold=%s)", len(gaps), threshold)
    return gaps


def validate_time_coverage(
    timestamps: pd.Series,
    user_start: datetime,
    user_end: datetime,
    config: FlowConfig,
    next_file_start: datetime | None = None,
) -> CoverageValidation:
    """Check whether *timestamps* fully cover ``[user_start, user_end]``.

    Returns a :class:`CoverageValidation` with explicit partial-coverage
    diagnostics, missing head/tail, internal gaps, and next-file info.
    """
    if timestamps.empty:
        return CoverageValidation(
            requested_start=user_start,
            requested_end=user_end,
            actual_start=None,
            actual_end=None,
            is_fully_covered=False,
            missing_head=user_end - user_start,
            missing_tail=user_end - user_start,
            gaps=[],
            next_file_start=next_file_start,
        )

    actual_start = timestamps.min().to_pydatetime()
    actual_end = timestamps.max().to_pydatetime()

    missing_head: timedelta | None = None
    if actual_start > user_start:
        missing_head = actual_start - user_start

    missing_tail: timedelta | None = None
    if actual_end < user_end:
        missing_tail = user_end - actual_end

    gaps = detect_gaps(timestamps, config) if config.gap_detection else []

    is_fully_covered = (
        missing_head is None
        and missing_tail is None
        and len(gaps) == 0
    )

    return CoverageValidation(
        requested_start=user_start,
        requested_end=user_end,
        actual_start=actual_start,
        actual_end=actual_end,
        is_fully_covered=is_fully_covered,
        missing_head=missing_head,
        missing_tail=missing_tail,
        gaps=gaps,
        next_file_start=next_file_start,
    )


def build_coverage_report(
    validation: CoverageValidation,
) -> str:
    """Generate a human-readable coverage report from a
    :class:`CoverageValidation` result.
    """
    lines: list[str] = []
    lines.append("=== Coverage Report ===")
    lines.append(f"Requested: {validation.requested_start} -> {validation.requested_end}")

    if validation.actual_start is None:
        lines.append("")
        lines.append("No data found in the requested window.")
        if validation.next_file_start is not None:
            lines.append(f"Next file starts at: {validation.next_file_start}")
        else:
            lines.append("No further files found.")
        return "\n".join(lines)

    lines.append(f"Actual:    {validation.actual_start} -> {validation.actual_end}")
    lines.append("")

    # -- Coverage segments ------------------------------------------------
    lines.append("Coverage:")

    if validation.is_fully_covered:
        span = validation.actual_end - validation.actual_start
        lines.append(f"  [OK] Continuous: {validation.actual_start} -> {validation.actual_end} ({span})")
    else:
        if validation.missing_head:
            lines.append(
                f"  [OK] Continuous: {validation.actual_start} -> {validation.actual_end}"
            )
        else:
            lines.append(
                f"  [OK] Continuous: {validation.requested_start} -> {validation.actual_end}"
            )

        if validation.gaps:
            # Detailed gap listing embedded in coverage
            cursor = validation.actual_start
            total_covered = timedelta()
            total_gap = timedelta()
            segment_lines: list[str] = []

            for gap in validation.gaps:
                covered = gap.gap_start - cursor
                total_covered += covered
                segment_lines.append(
                    f"  [OK] Covered:  {cursor} -> {gap.gap_start} ({covered})"
                )
                segment_lines.append(
                    f"  [!!] Gap:      {gap.gap_start} -> {gap.gap_end} ({gap.duration})"
                )
                total_gap += gap.duration
                cursor = gap.gap_end

            final = validation.actual_end - cursor
            total_covered += final
            segment_lines.append(
                f"  [OK] Covered:  {cursor} -> {validation.actual_end} ({final})"
            )

            # Replace the single continuous line with detailed segments
            lines.pop()
            lines.extend(segment_lines)

    # -- Gaps / missing sections ------------------------------------------
    lines.append("")
    lines.append("Gaps:")

    has_issues = False

    if validation.missing_head:
        has_issues = True
        lines.append(
            f"  [!!] Missing head: {validation.requested_start} -> "
            f"{validation.actual_start} ({validation.missing_head})"
        )

    if validation.missing_tail:
        has_issues = True
        lines.append(
            f"  [!!] Missing tail: {validation.actual_end} -> "
            f"{validation.requested_end} ({validation.missing_tail})"
        )

    if validation.gaps and not (validation.missing_head or validation.missing_tail):
        has_issues = True

    if not has_issues and not validation.gaps:
        lines.append("  None")

    # -- Additional info --------------------------------------------------
    lines.append("")
    lines.append("Additional:")
    if validation.next_file_start is not None:
        lines.append(f"  Next file starts at: {validation.next_file_start}")
    else:
        lines.append("  No further files found after the downloaded range.")

    # -- Summary ----------------------------------------------------------
    lines.append("")
    requested = validation.requested_end - validation.requested_start
    if validation.actual_start and validation.actual_end:
        actual_span = validation.actual_end - max(validation.actual_start, validation.requested_start)
        if actual_span < timedelta():
            actual_span = timedelta()
        pct = (actual_span / requested * 100) if requested.total_seconds() > 0 else 0
        lines.append(f"Coverage: {actual_span} / {requested} ({pct:.1f}%)")

        if validation.gaps:
            total_gap = sum((g.duration for g in validation.gaps), timedelta())
            lines.append(f"Internal gaps: {len(validation.gaps)} gaps, {total_gap} uncovered")

    return "\n".join(lines)


def build_rt_flow_report(
    file_ranges: list[tuple[str, datetime, datetime]],
    user_start: datetime,
    user_end: datetime,
) -> str:
    """Build a per-file report for RT flow (overlap-based, no merging).

    Args:
        file_ranges: list of ``(filename, min_ts, max_ts)`` tuples.
    """
    lines: list[str] = []
    lines.append("=== RT Flow File Report ===")
    lines.append(f"Requested: {user_start} -> {user_end}")
    lines.append(f"Files returned: {len(file_ranges)}")
    lines.append("")

    for fname, mn, mx in file_ranges:
        span = mx - mn
        short = fname.rsplit("/", 1)[-1] if "/" in fname else fname
        lines.append(f"  - {short}: {mn} -> {mx}  ({span})")

    return "\n".join(lines)
