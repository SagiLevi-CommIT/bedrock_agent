"""Vendored cs_downloader — utilities for parsing CardiacSense S3 keys,
probing actual signal time ranges, listing patient files efficiently, and
merging time-windowed file sets.

Source: C:/Users/SagiLevi/Documents/Git/CardiacSense-s3-downloader-tool
       commit 31fcc29085cd7d93f098063418d96699990e9ef8 (2026-04-29)

The vendored copy keeps `core/{time_utils,probe,boundary,s3_client,gap_detector,
downloader}.py` plus a stripped `config.py` (only the FlowConfig + GeneralConfig
dataclasses and per-flow defaults; the original credential/JSON loading is
omitted — bedrock_agent uses IAM task-role credentials via the default boto3
chain).
"""

from .config import (
    AppConfig,
    FlowConfig,
    GeneralConfig,
    default_app_config,
    default_flows,
)
from .time_utils import (
    extract_filename_epoch,
    epoch_ms_to_datetime,
    parse_sampling_time,
)
from .probe import probe_time_range, parallel_probe
from .s3_client import list_patient_files, FileInfo
from .boundary import find_boundaries, find_boundary
from .downloader import (
    download_and_filter,
    download_and_merge_inmemory,
    MergeResult,
    InMemoryMergeResult,
)
from .gap_detector import detect_gaps, validate_time_coverage

__all__ = [
    "AppConfig",
    "FlowConfig",
    "GeneralConfig",
    "default_app_config",
    "default_flows",
    "extract_filename_epoch",
    "epoch_ms_to_datetime",
    "parse_sampling_time",
    "probe_time_range",
    "parallel_probe",
    "list_patient_files",
    "FileInfo",
    "find_boundaries",
    "find_boundary",
    "download_and_filter",
    "download_and_merge_inmemory",
    "MergeResult",
    "InMemoryMergeResult",
    "detect_gaps",
    "validate_time_coverage",
]
