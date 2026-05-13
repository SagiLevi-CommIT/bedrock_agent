"""boto3 S3 session factory, credential validation, and patient file listing."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config as BotoConfig

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

from .config import AppConfig, FlowConfig
from .time_utils import epoch_ms_to_datetime, extract_filename_epoch

logger = logging.getLogger(__name__)


@dataclass
class FileInfo:
    """Lightweight metadata for a single S3 CSV object."""

    key: str
    size: int
    filename_epoch_ms: int
    filename_epoch_dt: datetime


def create_s3_client(config: AppConfig, flow_config: FlowConfig | None = None):
    """Create a boto3 S3 client with adaptive retry and connection pooling."""
    max_pool = flow_config.max_parallel_downloads if flow_config else 10

    boto_cfg = BotoConfig(
        region_name=config.aws_region,
        retries={"max_attempts": config.general.retry_attempts, "mode": "adaptive"},
        max_pool_connections=max_pool,
        connect_timeout=5,
        read_timeout=30,
    )

    session = boto3.Session(
        aws_access_key_id=config.aws_access_key_id or None,
        aws_secret_access_key=config.aws_secret_access_key or None,
        region_name=config.aws_region,
    )
    return session.client("s3", config=boto_cfg)


def validate_credentials(client, bucket: str) -> bool:
    """Quick check: can we list at least one object in the bucket prefix?"""
    try:
        resp = client.list_objects_v2(
            Bucket=bucket,
            Prefix="rearrangement/",
            MaxKeys=1,
        )
        return resp.get("KeyCount", 0) >= 0
    except Exception:
        logger.exception("Credential validation failed")
        return False


def list_patient_files(
    client,
    bucket: str,
    flow: str,
    patient_id: int,
    flow_config: FlowConfig | None = None,
    epoch_start_ms: int | None = None,
    epoch_end_ms: int | None = None,
    cancel_event: threading.Event | None = None,
) -> list[FileInfo]:
    """List CSV files for a given patient, sorted by filename epoch ascending.

    Uses a tight prefix to leverage S3 server-side filtering::

        rearrangement/{flow}/{flow}_{patient_id}_

    When *epoch_start_ms* is provided, uses ``StartAfter`` to skip files
    whose key sorts before the earliest interesting epoch, dramatically
    reducing LIST time for large file sets.
    """
    prefix = f"rearrangement/{flow}/{flow}_{patient_id}_"
    logger.info("Listing S3 objects: bucket=%s prefix=%s", bucket, prefix)

    kwargs_base: dict = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": 1000}

    if epoch_start_ms is not None:
        start_after = f"rearrangement/{flow}/{flow}_{patient_id}_{epoch_start_ms}"
        kwargs_base["StartAfter"] = start_after
        logger.info("Using StartAfter=%s to skip old files", start_after)

    files: list[FileInfo] = []
    continuation_token: str | None = None

    while True:
        if cancel_event is not None and cancel_event.is_set():
            logger.info("Listing cancelled by user after %d files", len(files))
            break

        kwargs = dict(kwargs_base)
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token

        resp = client.list_objects_v2(**kwargs)

        for obj in resp.get("Contents", []):
            key: str = obj["Key"]
            if not key.endswith(".csv"):
                continue
            try:
                epoch_ms = extract_filename_epoch(key)
            except ValueError:
                logger.warning("Skipping unrecognized filename: %s", key)
                continue

            if epoch_end_ms is not None and epoch_ms > epoch_end_ms:
                logger.info(
                    "Stopping listing early: file epoch %d > end %d",
                    epoch_ms, epoch_end_ms,
                )
                files.sort(key=lambda f: f.filename_epoch_ms)
                logger.info("Found %d CSV files for patient %d in %s", len(files), patient_id, flow)
                return files

            files.append(
                FileInfo(
                    key=key,
                    size=obj["Size"],
                    filename_epoch_ms=epoch_ms,
                    filename_epoch_dt=epoch_ms_to_datetime(epoch_ms),
                )
            )

        if resp.get("IsTruncated"):
            continuation_token = resp["NextContinuationToken"]
        else:
            break

    files.sort(key=lambda f: f.filename_epoch_ms)
    logger.info("Found %d CSV files for patient %d in %s", len(files), patient_id, flow)
    return files
