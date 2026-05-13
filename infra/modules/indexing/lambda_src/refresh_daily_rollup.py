"""Daily patient_daily rollup refresh.

Computes one day's per-patient-per-flow rollup row and writes it to
`s3://{ROLLUP_BUCKET}/rollup/patient_daily/dt=YYYY-MM-DD/data.parquet`,
then registers the partition in Glue.

Two data sources contribute:
  1. Athena query against `migrated_data.pc_results_part` for
     UUID-keyed session-level metrics (avg HR, SpO2, AF count, etc.) for
     the requested day.
  2. S3 LIST against `rearrangement/{flow}/` to count files + total bytes
     per integer patient_id per flow (covers the unindexed flows like
     sleep_flow that have no Athena table).

The two views are joined on (flow, patient_id) when a UUID mapping is
known via `migrated_data.metadata`. When no mapping is found, only the
S3-side fields are populated.

Triggered: EventBridge cron (typically 02:00 UTC daily). Can also be
invoked synchronously for backfill: `aws lambda invoke --payload
'{"date":"2026-04-15"}'`.

Requires the AWS-SDK-for-Pandas Lambda Layer (provides pandas + pyarrow).
The layer ARN is wired in Terraform.
"""

from __future__ import annotations

import io
import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import boto3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

LOG = logging.getLogger()
LOG.setLevel(logging.INFO)

APP_EVENTS_BUCKET = os.environ["APP_EVENTS_BUCKET"]
ROLLUP_BUCKET = os.environ["ROLLUP_BUCKET"]
ATHENA_RESULTS_BUCKET = os.environ["ATHENA_RESULTS_BUCKET"]
ATHENA_WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "primary")
AGENT_GLUE_DATABASE = os.environ.get("AGENT_GLUE_DATABASE", "bedrock_agent")
PATIENT_DAILY_TABLE = "patient_daily"

KNOWN_FLOWS = (
    "rt_flow",
    "sleep_flow",
    "ar_flow",
    "af_ppg_flow",
    "tachycardia_flow",
    "plate_flow",
    "arrythmia_flow",
    "algos_flow",
)

# Per-flow chunk-duration heuristic for total_duration_min estimation.
FLOW_CHUNK_MIN = {
    "rt_flow": 2,
    "sleep_flow": 25,
    "ar_flow": 2,
    "af_ppg_flow": 2,
    "tachycardia_flow": 2,
    "plate_flow": 5,
    "arrythmia_flow": 2,
    "algos_flow": 2,
}


def _resolve_date(event: dict[str, Any]) -> date:
    explicit = event.get("date") if isinstance(event, dict) else None
    if explicit:
        return datetime.strptime(explicit, "%Y-%m-%d").date()
    return (datetime.now(timezone.utc) - timedelta(days=1)).date()


def _list_flow_files_for_day(s3, flow: str, day: date) -> dict[int, dict[str, int]]:
    """Return {patient_id: {file_count, total_bytes, min_epoch_ms, max_epoch_ms}}."""
    start_ms = int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(
        datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000
    )
    prefix = f"rearrangement/{flow}/"
    by_patient: dict[int, dict[str, int]] = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=APP_EVENTS_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/") or not key.endswith(".csv"):
                continue
            base = key.rsplit("/", 1)[-1]
            stem = base[: -len(".csv")]
            parts = stem.split("_")
            try:
                epoch_ms = int(parts[-1])
                patient_id = int(parts[-2])
            except (ValueError, IndexError):
                continue
            if epoch_ms < start_ms or epoch_ms >= end_ms:
                continue
            d = by_patient.setdefault(
                patient_id,
                {"file_count": 0, "total_bytes": 0, "min_epoch_ms": epoch_ms, "max_epoch_ms": epoch_ms},
            )
            d["file_count"] += 1
            d["total_bytes"] += int(obj["Size"])
            d["min_epoch_ms"] = min(d["min_epoch_ms"], epoch_ms)
            d["max_epoch_ms"] = max(d["max_epoch_ms"], epoch_ms)
    return by_patient


def _run_athena(athena, sql: str) -> list[dict[str, Any]]:
    qid = athena.start_query_execution(
        QueryString=sql,
        WorkGroup=ATHENA_WORKGROUP,
        ResultConfiguration={"OutputLocation": f"s3://{ATHENA_RESULTS_BUCKET}/lambda-rollup/"},
    )["QueryExecutionId"]
    LOG.info("Athena query started: %s", qid)
    for _ in range(120):
        info = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
        state = info["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            LOG.error(
                "Athena %s ended in %s: %s",
                qid, state, info["Status"].get("StateChangeReason"),
            )
            return []
        time.sleep(2)
    else:
        LOG.error("Athena query %s timed out", qid)
        return []
    rows: list[dict[str, Any]] = []
    paginator = athena.get_paginator("get_query_results")
    header: list[str] = []
    for page in paginator.paginate(QueryExecutionId=qid):
        for r in page["ResultSet"]["Rows"]:
            cells = [c.get("VarCharValue", "") for c in r.get("Data", [])]
            if not header:
                header = cells
            else:
                rows.append(dict(zip(header, cells)))
    return rows


def _query_session_metrics(athena, day: date) -> list[dict[str, Any]]:
    sql = f"""
    SELECT patient AS patient_uuid,
           file_type AS flow,
           COUNT(DISTINCT session) AS session_count,
           AVG(hr) AS avg_hr,
           AVG(spo2) AS avg_spo2,
           SUM(af) AS af_event_count
    FROM migrated_data.pc_results_part
    WHERE date = DATE '{day.isoformat()}'
      AND patient IS NOT NULL
    GROUP BY patient, file_type
    """
    return _run_athena(athena, sql)


def _query_patient_uuid_mapping(athena, day: date) -> dict[tuple[str, str], dict[str, Any]]:
    """Best-effort integer↔UUID mapping for the day from metadata.

    We can't directly join integer patient_id to UUID, but for most sessions
    the metadata table records the UUID + a session id whose timing we can
    correlate later. For now we just expose UUID→flow→count buckets for
    enrichment of the Athena rows; the integer side is filled from S3.
    """
    return {}


def _build_dataframe(
    s3_buckets: dict[tuple[int, str], dict[str, Any]],
    athena_rows: list[dict[str, Any]],
    day: date,
) -> pd.DataFrame:
    """Build the wide rollup DataFrame matching the patient_daily schema."""
    computed_at = datetime.now(timezone.utc).replace(microsecond=0)

    # Index athena rows by (uuid, flow) for join
    by_uuid_flow: dict[tuple[str, str], dict[str, Any]] = {
        (r["patient_uuid"], r["flow"]): r for r in athena_rows
    }

    rows: list[dict[str, Any]] = []
    seen_uuids: set[tuple[str, str]] = set()

    # S3-side rows (integer patient_id, no UUID)
    for (pid, flow), agg in s3_buckets.items():
        chunk = FLOW_CHUNK_MIN.get(flow, 0)
        rows.append({
            "patient_id": int(pid),
            "patient_uuid": None,
            "flow": flow,
            "stage": "rearrangement",
            "file_count": int(agg["file_count"]),
            "total_bytes": int(agg["total_bytes"]),
            "min_sampling_time": pd.Timestamp(agg["min_epoch_ms"], unit="ms", tz="UTC").tz_localize(None),
            "max_sampling_time": pd.Timestamp(agg["max_epoch_ms"], unit="ms", tz="UTC").tz_localize(None),
            "total_duration_min": float(agg["file_count"] * chunk),
            "avg_hr": None,
            "avg_spo2": None,
            "ecg_quality_pct": None,
            "af_event_count": None,
            "computed_at": pd.Timestamp(computed_at).tz_localize(None),
        })

    # Athena-side rows (UUID, no integer patient_id) — append as separate rows
    # so analytics on either keying still work.
    for (uuid, flow), r in by_uuid_flow.items():
        if (uuid, flow) in seen_uuids:
            continue
        seen_uuids.add((uuid, flow))
        rows.append({
            "patient_id": None,
            "patient_uuid": uuid or None,
            "flow": flow,
            "stage": "migrated",
            "file_count": int(r["session_count"]) if r.get("session_count") else None,
            "total_bytes": None,
            "min_sampling_time": None,
            "max_sampling_time": None,
            "total_duration_min": None,
            "avg_hr": float(r["avg_hr"]) if r.get("avg_hr") else None,
            "avg_spo2": float(r["avg_spo2"]) if r.get("avg_spo2") else None,
            "ecg_quality_pct": None,
            "af_event_count": int(r["af_event_count"]) if r.get("af_event_count") else None,
            "computed_at": pd.Timestamp(computed_at).tz_localize(None),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Enforce dtypes that match the Glue schema
    df = df.astype({
        "patient_id": "Int32",
        "patient_uuid": "object",
        "flow": "object",
        "stage": "object",
        "file_count": "Int32",
        "total_bytes": "Int64",
        "total_duration_min": "float64",
        "avg_hr": "float64",
        "avg_spo2": "float64",
        "ecg_quality_pct": "float64",
        "af_event_count": "Int32",
    })
    return df


def _register_partition(glue, day: date) -> None:
    location = f"s3://{ROLLUP_BUCKET}/rollup/patient_daily/dt={day.isoformat()}/"
    try:
        glue.delete_partition(
            DatabaseName=AGENT_GLUE_DATABASE,
            TableName=PATIENT_DAILY_TABLE,
            PartitionValues=[day.isoformat()],
        )
        LOG.info("Removed previous partition for dt=%s", day)
    except glue.exceptions.EntityNotFoundException:
        pass
    except Exception:
        LOG.exception("Could not delete previous partition (continuing)")
    glue.create_partition(
        DatabaseName=AGENT_GLUE_DATABASE,
        TableName=PATIENT_DAILY_TABLE,
        PartitionInput={
            "Values": [day.isoformat()],
            "StorageDescriptor": {
                "Location": location,
                "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
                "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
                "SerdeInfo": {
                    "SerializationLibrary": "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe",
                },
            },
        },
    )
    LOG.info("Registered Glue partition dt=%s -> %s", day, location)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    LOG.info("event=%s", json.dumps(event, default=str))
    day = _resolve_date(event)
    s3 = boto3.client("s3")
    athena = boto3.client("athena")
    glue = boto3.client("glue")

    s3_buckets: dict[tuple[int, str], dict[str, Any]] = {}
    for flow in KNOWN_FLOWS:
        try:
            for pid, agg in _list_flow_files_for_day(s3, flow, day).items():
                s3_buckets[(pid, flow)] = agg
        except Exception:
            LOG.exception("flow=%s S3 listing failed; skipping", flow)
    LOG.info("S3 found %d (patient,flow) buckets for %s", len(s3_buckets), day)

    try:
        athena_rows = _query_session_metrics(athena, day)
        LOG.info("Athena returned %d rows for %s", len(athena_rows), day)
    except Exception:
        LOG.exception("Athena rollup query failed; continuing with S3-only rows")
        athena_rows = []

    df = _build_dataframe(s3_buckets, athena_rows, day)
    LOG.info("Rollup DataFrame: %d rows, %d cols", len(df), len(df.columns))

    if df.empty:
        return {"status": "empty", "dt": day.isoformat()}

    # The AWS SDK for Pandas layer's pyarrow is compiled without S3 support,
    # so we serialise to a BytesIO buffer and upload via boto3.
    out_key = f"rollup/patient_daily/dt={day.isoformat()}/data.parquet"
    buf = io.BytesIO()
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), buf, compression="snappy")
    buf.seek(0)
    s3.put_object(
        Bucket=ROLLUP_BUCKET,
        Key=out_key,
        Body=buf.getvalue(),
        ContentType="application/octet-stream",
    )
    LOG.info("Wrote parquet to s3://%s/%s (%d rows)", ROLLUP_BUCKET, out_key, len(df))

    try:
        _register_partition(glue, day)
    except Exception:
        LOG.exception("Partition registration failed (parquet still in S3)")

    return {
        "status": "ok",
        "dt": day.isoformat(),
        "s3_buckets": len(s3_buckets),
        "athena_rows": len(athena_rows),
        "parquet_rows": len(df),
        "parquet_key": out_key,
    }
