"""Timestamp parsing and filename epoch extraction utilities."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_FILENAME_EPOCH_RE = re.compile(r"_(\d{10,13})\.csv$")


def extract_filename_epoch(key: str) -> int:
    """Extract epoch_ms from an S3 key like ``sleep_flow_1000_1734392368381.csv``.

    Returns epoch in **milliseconds** regardless of whether the filename
    stores seconds or milliseconds.
    """
    m = _FILENAME_EPOCH_RE.search(key)
    if not m:
        raise ValueError(f"Cannot extract epoch from key: {key!r}")
    val = int(m.group(1))
    if val < 1e12:
        val *= 1000
    return val


def epoch_ms_to_datetime(epoch_ms: int) -> datetime:
    return datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)


def parse_sampling_time(series: pd.Series) -> pd.Series:
    """Auto-detect format and convert a ``sampling_time`` column to UTC datetimes."""
    if series.empty:
        return pd.Series(dtype="datetime64[ns, UTC]")

    sample = series.dropna().iloc[0] if len(series.dropna()) > 0 else None
    if sample is None:
        return pd.Series(dtype="datetime64[ns, UTC]")

    if isinstance(sample, (int, float, np.integer, np.floating)) or (
        isinstance(sample, str) and sample.replace(".", "", 1).isdigit()
    ):
        val = float(sample)
        if val > 1e12:
            return pd.to_datetime(series.astype(float), unit="ms", utc=True)
        elif val > 1e9:
            return pd.to_datetime(series.astype(float), unit="s", utc=True)
        else:
            raise ValueError(f"sampling_time value {val} too small to be epoch")
    else:
        return pd.to_datetime(series, utc=True)
