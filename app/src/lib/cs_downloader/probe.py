"""Lightweight time-range probing via HTTP Range-GET requests.

Reads only the first and last ``probe_bytes`` of a CSV to extract
the min/max ``sampling_time`` without downloading the full file.
"""

from __future__ import annotations

import io
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd

from .config import GeneralConfig
from .time_utils import parse_sampling_time

logger = logging.getLogger(__name__)

SAMPLING_TIME_COL = "sampling_time"


def _parse_ts_from_line(header: list[str], line: str) -> datetime | None:
    """Extract a single sampling_time value from a CSV line."""
    parts = line.strip().split(",")
    try:
        idx = header.index(SAMPLING_TIME_COL)
    except ValueError:
        return None
    if len(parts) <= idx:
        return None
    raw = parts[idx].strip()
    if not raw:
        return None
    ts_series = parse_sampling_time(pd.Series([raw]))
    if ts_series.empty or pd.isna(ts_series.iloc[0]):
        return None
    return ts_series.iloc[0].to_pydatetime()


def probe_time_range(
    client,
    bucket: str,
    key: str,
    probe_bytes: int = 8192,
) -> tuple[datetime, datetime]:
    """Return ``(min_sampling_time, max_sampling_time)`` by reading
    only the first and last ``probe_bytes`` of the CSV.

    Cost: 1 HeadObject + 2 Range-GET requests (~16 KB total).
    """
    head = client.head_object(Bucket=bucket, Key=key)
    file_size = head["ContentLength"]

    # --- First chunk: header + first data rows -> min time ---
    first_bytes = min(probe_bytes, file_size)
    first_resp = client.get_object(
        Bucket=bucket, Key=key, Range=f"bytes=0-{first_bytes - 1}"
    )
    first_chunk = first_resp["Body"].read().decode("utf-8", errors="replace")
    lines = first_chunk.split("\n")
    header = [h.strip() for h in lines[0].split(",")]

    first_ts: datetime | None = None
    for line in lines[1:]:
        if not line.strip():
            continue
        first_ts = _parse_ts_from_line(header, line)
        if first_ts is not None:
            break

    # --- Last chunk: last data rows -> max time ---
    last_start = max(0, file_size - probe_bytes)
    if last_start == 0:
        # File fits in a single probe; parse all lines
        last_chunk = first_chunk
    else:
        last_resp = client.get_object(
            Bucket=bucket, Key=key, Range=f"bytes={last_start}-{file_size - 1}"
        )
        last_chunk = last_resp["Body"].read().decode("utf-8", errors="replace")

    last_lines = last_chunk.split("\n")

    last_ts: datetime | None = None
    for line in reversed(last_lines):
        if not line.strip():
            continue
        ts = _parse_ts_from_line(header, line)
        if ts is not None:
            last_ts = ts
            break

    if first_ts is None or last_ts is None:
        raise ValueError(
            f"Could not extract sampling_time from {key} "
            f"(first={first_ts}, last={last_ts})"
        )

    logger.debug("Probed %s -> [%s, %s]", key, first_ts, last_ts)
    return (first_ts, last_ts)


def parallel_probe(
    client,
    bucket: str,
    keys: list[str],
    max_workers: int = 5,
    probe_bytes: int = 8192,
    progress_callback=None,
) -> dict[str, tuple[datetime, datetime]]:
    """Probe multiple files concurrently, returning a key -> (min_ts, max_ts) map.

    If *progress_callback* is given, it is called as ``cb(done, total)`` after
    each probe completes so callers can stream progress to the UI.
    """
    results: dict[str, tuple[datetime, datetime]] = {}
    total = len(keys)
    done = 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_key = {
            pool.submit(probe_time_range, client, bucket, k, probe_bytes): k
            for k in keys
        }
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            try:
                results[key] = future.result()
            except Exception:
                logger.exception("Probe failed for %s", key)
            done += 1
            if progress_callback is not None:
                try:
                    progress_callback(done, total)
                except Exception:
                    logger.exception("progress_callback failed")

    return results
