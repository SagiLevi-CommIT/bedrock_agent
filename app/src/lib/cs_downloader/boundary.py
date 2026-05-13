"""Boundary search: find the left/right files whose real sampling_time
covers the user-requested time window.

Uses bisect for O(log n) heuristic positioning, then iterative expansion
with a shared probe cache to minimise S3 calls.
"""

from __future__ import annotations

import bisect
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable

from .config import FlowConfig
from .probe import parallel_probe, probe_time_range
from .s3_client import FileInfo

logger = logging.getLogger(__name__)

ProbeCache = dict[str, tuple[datetime, datetime]]


def _epoch_list(files: list[FileInfo]) -> list[int]:
    return [f.filename_epoch_ms for f in files]


def find_boundary(
    client,
    bucket: str,
    sorted_files: list[FileInfo],
    target_time: datetime,
    direction: str,
    config: FlowConfig,
    cache: ProbeCache,
    probe_bytes: int = 8192,
    cancel_event: threading.Event | None = None,
) -> int | None:
    """Find the index of the boundary file whose real ``sampling_time``
    covers *target_time*.

    Args:
        direction: ``'left'`` searches leftward from the heuristic
            position; ``'right'`` searches rightward.
        cache: mutable dict shared between left/right searches so
            probed ranges are never fetched twice.

    Returns:
        Index into *sorted_files*, or ``None`` if not found within
        ``config.max_expansions`` rounds.
    """
    if not sorted_files:
        return None

    target_epoch_ms = int(target_time.timestamp() * 1000)
    lag_offset_ms = config.typical_upload_lag_min * 60 * 1000
    epochs = _epoch_list(sorted_files)

    if direction == "left":
        heuristic_epoch = target_epoch_ms - lag_offset_ms
    else:
        heuristic_epoch = target_epoch_ms + lag_offset_ms

    heuristic_idx = bisect.bisect_left(epochs, heuristic_epoch)
    heuristic_idx = max(0, min(heuristic_idx, len(sorted_files) - 1))

    search_radius = config.initial_search_batch

    # Maximum tolerable distance between a file's range edge and the target
    # to consider it a "near-miss" boundary.
    near_threshold = timedelta(
        minutes=config.estimated_chunk_duration_min * config.expansion_factor * (config.max_expansions + 1)
    )

    for expansion in range(config.max_expansions + 1):
        if cancel_event is not None and cancel_event.is_set():
            logger.info("Boundary %s search cancelled", direction)
            return None

        if direction == "left":
            batch_start = max(0, heuristic_idx - search_radius)
            batch_end = min(len(sorted_files), heuristic_idx + search_radius + 1)
        else:
            batch_start = max(0, heuristic_idx - search_radius)
            batch_end = min(len(sorted_files), heuristic_idx + search_radius + 1)

        batch = sorted_files[batch_start:batch_end]
        if not batch:
            break

        # Probe files not yet in cache
        uncached_keys = [f.key for f in batch if f.key not in cache]
        if uncached_keys:
            new_ranges = parallel_probe(
                client, bucket, uncached_keys,
                max_workers=min(len(uncached_keys), 5),
                probe_bytes=probe_bytes,
            )
            cache.update(new_ranges)

        # Check each file in the batch for exact containment first
        for i, f in enumerate(batch):
            rng = cache.get(f.key)
            if rng is None:
                continue
            file_min, file_max = rng
            if file_min <= target_time <= file_max:
                return batch_start + i

        # Second pass: look for the closest near-miss
        best_idx: int | None = None
        best_distance = timedelta.max

        for i, f in enumerate(batch):
            rng = cache.get(f.key)
            if rng is None:
                continue
            file_min, file_max = rng

            if direction == "left":
                # For left boundary, find file whose max is closest to (and >= ) target
                if file_max >= target_time:
                    dist = file_max - target_time
                    if dist < best_distance:
                        best_distance = dist
                        best_idx = batch_start + i
            else:
                # For right boundary, find file whose min is closest to (and <=) target
                # but whose max is also reasonably close (within near_threshold)
                if file_min <= target_time and (target_time - file_max) < near_threshold:
                    dist = target_time - file_min
                    if dist < best_distance:
                        best_distance = dist
                        best_idx = batch_start + i

        if best_idx is not None:
            return best_idx

        # Expand search radius
        search_radius = int(search_radius * config.expansion_factor)
        if direction == "left":
            heuristic_idx = max(0, heuristic_idx - search_radius)
        else:
            heuristic_idx = min(len(sorted_files) - 1, heuristic_idx + search_radius)

        logger.debug(
            "Boundary %s expansion #%d: radius=%d, heuristic_idx=%d",
            direction, expansion + 1, search_radius, heuristic_idx,
        )

    logger.warning("Boundary %s not found after %d expansions", direction, config.max_expansions)
    return None


def find_boundaries(
    client,
    bucket: str,
    sorted_files: list[FileInfo],
    user_start: datetime,
    user_end: datetime,
    config: FlowConfig,
    probe_bytes: int = 8192,
    progress_callback: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[int | None, int | None, ProbeCache]:
    """Find both left and right boundary indices, sharing a probe cache.

    Returns ``(left_idx, right_idx, cache)`` where *cache* maps S3 keys
    to ``(min_ts, max_ts)`` for every file probed during the search.
    """
    cache: ProbeCache = {}

    if progress_callback:
        progress_callback("Searching for left boundary...")
    left = find_boundary(
        client, bucket, sorted_files, user_start,
        "left", config, cache, probe_bytes,
        cancel_event=cancel_event,
    )
    if progress_callback:
        if left is not None:
            rng = cache.get(sorted_files[left].key, (None, None))
            progress_callback(
                f"Left boundary: file #{left} ({rng[0]})"
            )
        else:
            progress_callback("Left boundary not found")

    if cancel_event is not None and cancel_event.is_set():
        return left, None, cache

    if progress_callback:
        progress_callback("Searching for right boundary...")
    right = find_boundary(
        client, bucket, sorted_files, user_end,
        "right", config, cache, probe_bytes,
        cancel_event=cancel_event,
    )
    if progress_callback:
        if right is not None:
            rng = cache.get(sorted_files[right].key, (None, None))
            progress_callback(
                f"Right boundary: file #{right} ({rng[1]})"
            )
        else:
            progress_callback("Right boundary not found")

    logger.info(
        "Boundaries: left=%s right=%s  (probed %d files total)",
        left, right, len(cache),
    )
    return left, right, cache
