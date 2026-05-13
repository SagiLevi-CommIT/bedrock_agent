"""Vendored config dataclasses for cs_downloader.

In the original tool, config.py also loaded AWS credentials from a JSON file
on disk. In the bedrock_agent runtime we pick up credentials from the IAM
task role (via boto3's default credential chain) — so this vendored copy
keeps only the flow heuristics and general settings; credential plumbing is
omitted.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FlowConfig:
    s3_prefix: str
    file_pattern: str
    estimated_chunk_duration_min: int
    typical_upload_lag_min: int
    initial_search_offset_min: int
    initial_search_batch: int
    expansion_factor: float
    max_expansions: int
    max_parallel_downloads: int
    gap_detection: bool
    description: str
    gap_threshold_multiplier: float = 2.0
    overlap_tolerance_sec: int = 10
    listing_safety_multiplier: float = 2.0


@dataclass
class GeneralConfig:
    probe_bytes: int = 8192
    retry_attempts: int = 3
    retry_backoff_base: float = 1.0
    large_range_warning_days: int = 30
    default_output_dir: str = "./output"
    offline_mode: bool = False
    max_points_per_channel: int = 200_000
    plotlyjs_version: str = "2.35.2"


@dataclass
class AppConfig:
    flows: dict[str, FlowConfig] = field(default_factory=dict)
    general: GeneralConfig = field(default_factory=GeneralConfig)

    def get_flow(self, flow_name: str) -> FlowConfig:
        if flow_name not in self.flows:
            raise ValueError(
                f"Unknown flow: {flow_name!r}. Available: {list(self.flows)}"
            )
        return self.flows[flow_name]


def default_flows() -> dict[str, FlowConfig]:
    """Per-flow heuristics matching the production downloader."""
    return {
        "rt_flow": FlowConfig(
            s3_prefix="rearrangement/rt_flow/",
            file_pattern="rt_flow_{patient_id}_{epoch_ms}.csv",
            estimated_chunk_duration_min=2,
            typical_upload_lag_min=5,
            initial_search_offset_min=15,
            initial_search_batch=5,
            expansion_factor=2.0,
            max_expansions=5,
            max_parallel_downloads=10,
            gap_detection=False,
            description="Event-based, non-continuous",
            overlap_tolerance_sec=10,
        ),
        "sleep_flow": FlowConfig(
            s3_prefix="rearrangement/sleep_flow/",
            file_pattern="sleep_flow_{patient_id}_{epoch_ms}.csv",
            estimated_chunk_duration_min=25,
            typical_upload_lag_min=25,
            initial_search_offset_min=60,
            initial_search_batch=3,
            expansion_factor=2.0,
            max_expansions=5,
            max_parallel_downloads=10,
            gap_detection=True,
            gap_threshold_multiplier=2.0,
            description="Continuous monitoring",
            listing_safety_multiplier=3.0,
        ),
        "ar_flow": FlowConfig(
            s3_prefix="rearrangement/ar_flow/",
            file_pattern="ar_flow_{patient_id}_{epoch_ms}.csv",
            estimated_chunk_duration_min=2,
            typical_upload_lag_min=10,
            initial_search_offset_min=30,
            initial_search_batch=5,
            expansion_factor=2.0,
            max_expansions=5,
            max_parallel_downloads=10,
            gap_detection=False,
            description="Triggered arrhythmia recordings",
            overlap_tolerance_sec=10,
        ),
        "af_ppg_flow": FlowConfig(
            s3_prefix="rearrangement/af_ppg_flow/",
            file_pattern="af_ppg_flow_{patient_id}_{epoch_ms}.csv",
            estimated_chunk_duration_min=2,
            typical_upload_lag_min=10,
            initial_search_offset_min=30,
            initial_search_batch=5,
            expansion_factor=2.0,
            max_expansions=5,
            max_parallel_downloads=10,
            gap_detection=False,
            description="AF detection via PPG, triggered",
            overlap_tolerance_sec=10,
        ),
        "tachycardia_flow": FlowConfig(
            s3_prefix="rearrangement/tachycardia_flow/",
            file_pattern="tachycardia_flow_{patient_id}_{epoch_ms}.csv",
            estimated_chunk_duration_min=2,
            typical_upload_lag_min=10,
            initial_search_offset_min=30,
            initial_search_batch=5,
            expansion_factor=2.0,
            max_expansions=5,
            max_parallel_downloads=10,
            gap_detection=False,
            description="Tachycardia trigger recordings",
            overlap_tolerance_sec=10,
        ),
        "plate_flow": FlowConfig(
            s3_prefix="rearrangement/plate_flow/",
            file_pattern="plate_flow_{patient_id}_{epoch_ms}.csv",
            estimated_chunk_duration_min=5,
            typical_upload_lag_min=10,
            initial_search_offset_min=30,
            initial_search_batch=5,
            expansion_factor=2.0,
            max_expansions=5,
            max_parallel_downloads=10,
            gap_detection=False,
            description="Plate device continuous recordings",
            overlap_tolerance_sec=10,
        ),
        "arrythmia_flow": FlowConfig(  # 'arrythmia' is the actual S3 spelling
            s3_prefix="rearrangement/arrythmia_flow/",
            file_pattern="arrythmia_flow_{patient_id}_{epoch_ms}.csv",
            estimated_chunk_duration_min=2,
            typical_upload_lag_min=10,
            initial_search_offset_min=30,
            initial_search_batch=5,
            expansion_factor=2.0,
            max_expansions=5,
            max_parallel_downloads=10,
            gap_detection=False,
            description="Arrhythmia-flow recordings (distinct from ar_flow)",
            overlap_tolerance_sec=10,
        ),
        "algos_flow": FlowConfig(
            s3_prefix="rearrangement/algos_flow/",
            file_pattern="algos_flow_{patient_id}_{epoch_ms}.csv",
            estimated_chunk_duration_min=2,
            typical_upload_lag_min=10,
            initial_search_offset_min=30,
            initial_search_batch=5,
            expansion_factor=2.0,
            max_expansions=5,
            max_parallel_downloads=10,
            gap_detection=False,
            description="Experimental algorithm recordings",
            overlap_tolerance_sec=10,
        ),
    }


def default_app_config() -> AppConfig:
    return AppConfig(flows=default_flows(), general=GeneralConfig())
