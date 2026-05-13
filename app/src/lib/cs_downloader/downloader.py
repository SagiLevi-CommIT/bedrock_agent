"""Parallel full-file download, vectorized row filtering, incremental CSV merge,
and raw file download (no processing).
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from .config import FlowConfig
from .s3_client import FileInfo
from .time_utils import parse_sampling_time

logger = logging.getLogger(__name__)

SAMPLING_TIME_COL = "sampling_time"
_TS_INTERNAL = "_ts"


@dataclass
class MergeResult:
    rows_written: int = 0
    files_downloaded: int = 0
    files_with_data: int = 0
    output_path: str = ""


@dataclass
class RawDownloadResult:
    """Result of a raw (no-processing) download."""

    files_downloaded: int = 0
    output_dir: str = ""
    downloaded_paths: list[str] = field(default_factory=list)


@dataclass
class FileTimeRange:
    """Per-file time range used in rt_flow reports."""

    key: str
    local_path: str
    min_ts: datetime | None = None
    max_ts: datetime | None = None


# ─────────────────────────────────────────────────────────────────────
# Mode B: Processed single-file download (existing behaviour)
# ─────────────────────────────────────────────────────────────────────


def _download_and_filter_one(
    client,
    bucket: str,
    file_info: FileInfo,
    user_start: datetime,
    user_end: datetime,
) -> pd.DataFrame | None:
    """Download a single CSV, parse it, and return rows within the time window."""
    try:
        resp = client.get_object(Bucket=bucket, Key=file_info.key)
        body = resp["Body"].read()
    except Exception:
        logger.exception("Failed to download %s", file_info.key)
        return None

    try:
        df = pd.read_csv(io.BytesIO(body))
    except Exception:
        logger.exception("Failed to parse CSV %s", file_info.key)
        return None

    if df.empty or SAMPLING_TIME_COL not in df.columns:
        logger.warning("Skipping %s: empty or missing %s column", file_info.key, SAMPLING_TIME_COL)
        return None

    try:
        df[_TS_INTERNAL] = parse_sampling_time(df[SAMPLING_TIME_COL])
    except Exception:
        logger.exception("Failed to parse sampling_time in %s", file_info.key)
        return None

    ts_start = pd.Timestamp(user_start)
    ts_end = pd.Timestamp(user_end)
    if ts_start.tzinfo is None:
        ts_start = ts_start.tz_localize("UTC")
    if ts_end.tzinfo is None:
        ts_end = ts_end.tz_localize("UTC")
    mask = (df[_TS_INTERNAL] >= ts_start) & (df[_TS_INTERNAL] <= ts_end)
    filtered = df.loc[mask].copy()

    if filtered.empty:
        logger.debug("No rows in window for %s", file_info.key)
        return None

    return filtered


def download_and_filter(
    client,
    bucket: str,
    files: list[FileInfo],
    user_start: datetime,
    user_end: datetime,
    output_path: Path,
    config: FlowConfig,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> MergeResult:
    """Download files in parallel, filter rows, and write incrementally to *output_path*."""
    result = MergeResult(output_path=str(output_path))
    if not files:
        return result

    n_workers = min(len(files), config.max_parallel_downloads)
    header_written = False
    write_lock = threading.Lock()
    completed = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_fh = open(output_path, "w", newline="", encoding="utf-8")

    try:
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            future_to_file = {
                pool.submit(
                    _download_and_filter_one,
                    client, bucket, fi, user_start, user_end,
                ): fi
                for fi in files
            }

            for future in as_completed(future_to_file):
                if cancel_event and cancel_event.is_set():
                    logger.info("Download cancelled by user")
                    pool.shutdown(wait=False, cancel_futures=True)
                    break

                fi = future_to_file[future]
                result.files_downloaded += 1
                completed += 1

                if progress_callback:
                    progress_callback(completed, len(files))

                try:
                    df = future.result()
                except Exception:
                    logger.exception("Unexpected error processing %s", fi.key)
                    continue

                if df is None or df.empty:
                    continue

                result.files_with_data += 1

                with write_lock:
                    write_df = df.drop(columns=[_TS_INTERNAL], errors="ignore")
                    write_df.to_csv(
                        out_fh,
                        index=False,
                        header=not header_written,
                    )
                    header_written = True
                    result.rows_written += len(write_df)
    finally:
        out_fh.close()

    if result.rows_written > 0:
        _sort_and_dedup(output_path)
        final_df = pd.read_csv(output_path)
        result.rows_written = len(final_df)

    return result


# ─────────────────────────────────────────────────────────────────────
# Mode B (in-memory): produces a merged DataFrame without touching disk
# ─────────────────────────────────────────────────────────────────────


@dataclass
class InMemoryMergeResult:
    """Result of an in-memory download+merge for visualization."""

    merged_df: pd.DataFrame | None = None
    files_downloaded: int = 0
    files_with_data: int = 0
    rows: int = 0


def download_and_merge_inmemory(
    client,
    bucket: str,
    files: list[FileInfo],
    user_start: datetime,
    user_end: datetime,
    config: FlowConfig,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> InMemoryMergeResult:
    """Download files in parallel, filter rows, merge in memory (no disk).

    Same parallelism/cancel contract as :func:`download_and_filter` but
    returns a merged ``DataFrame`` instead of writing a CSV.  Rows are sorted
    by ``sampling_time`` and deduped on that column.
    """
    result = InMemoryMergeResult()
    if not files:
        result.merged_df = pd.DataFrame()
        return result

    n_workers = min(len(files), config.max_parallel_downloads)
    frames_lock = threading.Lock()
    frames: list[pd.DataFrame] = []
    completed = 0

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        future_to_file = {
            pool.submit(
                _download_and_filter_one,
                client, bucket, fi, user_start, user_end,
            ): fi
            for fi in files
        }

        for future in as_completed(future_to_file):
            if cancel_event and cancel_event.is_set():
                logger.info("In-memory download cancelled by user")
                pool.shutdown(wait=False, cancel_futures=True)
                break

            fi = future_to_file[future]
            result.files_downloaded += 1
            completed += 1

            if progress_callback:
                progress_callback(completed, len(files))

            try:
                df = future.result()
            except Exception:
                logger.exception("Unexpected error processing %s", fi.key)
                continue

            if df is None or df.empty:
                continue

            result.files_with_data += 1
            with frames_lock:
                frames.append(df.drop(columns=[_TS_INTERNAL], errors="ignore"))

    if not frames:
        result.merged_df = pd.DataFrame()
        return result

    merged = pd.concat(frames, ignore_index=True, sort=False)
    if SAMPLING_TIME_COL in merged.columns:
        merged["_ts_sort"] = parse_sampling_time(merged[SAMPLING_TIME_COL])
        merged = (
            merged.sort_values("_ts_sort")
            .drop_duplicates(subset=[SAMPLING_TIME_COL])
            .drop(columns=["_ts_sort"])
            .reset_index(drop=True)
        )
    result.merged_df = merged
    result.rows = len(merged)
    return result


# ─────────────────────────────────────────────────────────────────────
# Mode A: Raw file download (no merge/trim)
# ─────────────────────────────────────────────────────────────────────


def _download_raw_one(
    client,
    bucket: str,
    file_info: FileInfo,
    output_dir: Path,
) -> str | None:
    """Download a single CSV as-is to *output_dir*. Returns local path."""
    try:
        resp = client.get_object(Bucket=bucket, Key=file_info.key)
        body = resp["Body"].read()
    except Exception:
        logger.exception("Failed to download %s", file_info.key)
        return None

    filename = file_info.key.rsplit("/", 1)[-1]
    local_path = output_dir / filename
    local_path.write_bytes(body)
    return str(local_path)


def download_raw_files(
    client,
    bucket: str,
    files: list[FileInfo],
    output_dir: Path,
    config: FlowConfig,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> RawDownloadResult:
    """Download files as-is (no filtering / merging). Mode A."""
    result = RawDownloadResult(output_dir=str(output_dir))
    if not files:
        return result

    output_dir.mkdir(parents=True, exist_ok=True)
    n_workers = min(len(files), config.max_parallel_downloads)
    completed = 0

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        future_to_file = {
            pool.submit(_download_raw_one, client, bucket, fi, output_dir): fi
            for fi in files
        }

        for future in as_completed(future_to_file):
            if cancel_event and cancel_event.is_set():
                logger.info("Raw download cancelled")
                pool.shutdown(wait=False, cancel_futures=True)
                break

            completed += 1
            if progress_callback:
                progress_callback(completed, len(files))

            try:
                path = future.result()
            except Exception:
                logger.exception("Unexpected error in raw download")
                continue

            if path:
                result.files_downloaded += 1
                result.downloaded_paths.append(path)

    return result


# ─────────────────────────────────────────────────────────────────────
# RT Flow: download files and extract per-file time ranges
# ─────────────────────────────────────────────────────────────────────


def download_rt_files(
    client,
    bucket: str,
    files: list[FileInfo],
    output_dir: Path,
    config: FlowConfig,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[FileTimeRange]:
    """Download RT flow files as-is and extract per-file time ranges."""
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[FileTimeRange] = []
    n_workers = min(len(files), config.max_parallel_downloads)
    completed = 0
    lock = threading.Lock()

    def _download_one(fi: FileInfo) -> FileTimeRange:
        ftr = FileTimeRange(key=fi.key, local_path="")
        try:
            resp = client.get_object(Bucket=bucket, Key=fi.key)
            body = resp["Body"].read()
        except Exception:
            logger.exception("Failed to download %s", fi.key)
            return ftr

        filename = fi.key.rsplit("/", 1)[-1]
        local = output_dir / filename
        local.write_bytes(body)
        ftr.local_path = str(local)

        try:
            df = pd.read_csv(io.BytesIO(body))
            if SAMPLING_TIME_COL in df.columns and not df.empty:
                ts = parse_sampling_time(df[SAMPLING_TIME_COL])
                ftr.min_ts = ts.min().to_pydatetime()
                ftr.max_ts = ts.max().to_pydatetime()
        except Exception:
            logger.exception("Failed to parse time range for %s", fi.key)

        return ftr

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        future_to_file = {pool.submit(_download_one, fi): fi for fi in files}

        for future in as_completed(future_to_file):
            if cancel_event and cancel_event.is_set():
                pool.shutdown(wait=False, cancel_futures=True)
                break

            completed += 1
            if progress_callback:
                progress_callback(completed, len(files))

            try:
                ftr = future.result()
                with lock:
                    results.append(ftr)
            except Exception:
                logger.exception("RT download error")

    results.sort(key=lambda r: r.min_ts or datetime.min)
    return results


# ─────────────────────────────────────────────────────────────────────
# Sort + dedup helpers
# ─────────────────────────────────────────────────────────────────────


def _sort_and_dedup(path: Path) -> None:
    file_size = path.stat().st_size

    if file_size > 500 * 1024 * 1024:
        _sort_and_dedup_chunked(path)
        return

    df = pd.read_csv(path)
    if SAMPLING_TIME_COL not in df.columns:
        return

    df[_TS_INTERNAL] = parse_sampling_time(df[SAMPLING_TIME_COL])
    df.sort_values(_TS_INTERNAL, inplace=True)
    df.drop_duplicates(inplace=True)
    df.drop(columns=[_TS_INTERNAL], inplace=True)
    df.to_csv(path, index=False)
    logger.info("Sort+dedup complete: %d rows", len(df))


def _sort_and_dedup_chunked(path: Path, chunk_size: int = 100_000) -> None:
    chunks: list[pd.DataFrame] = []
    for chunk in pd.read_csv(path, chunksize=chunk_size):
        if SAMPLING_TIME_COL in chunk.columns:
            chunk[_TS_INTERNAL] = parse_sampling_time(chunk[SAMPLING_TIME_COL])
        chunks.append(chunk)

    if not chunks:
        return

    merged = pd.concat(chunks, ignore_index=True)
    if _TS_INTERNAL in merged.columns:
        merged.sort_values(_TS_INTERNAL, inplace=True)
        merged.drop(columns=[_TS_INTERNAL], inplace=True)
    merged.drop_duplicates(inplace=True)
    merged.to_csv(path, index=False)
    logger.info("Chunked sort+dedup complete: %d rows", len(merged))
