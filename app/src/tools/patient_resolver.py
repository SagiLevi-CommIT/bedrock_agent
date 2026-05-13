"""Patient identity resolution tools.

CardiacSense uses two distinct patient identifiers:
  - integer `patient_id` (e.g. 605) — in S3 filenames, default.rt_flow_metadata,
    eventdata.events, processed/cs_events_*.csv.
  - UUID `pUuid` (e.g. 925605c3-e25c-...) — in migrated_data.* tables.

The two are NOT derivable from each other. The canonical mapping is exposed
only via an internal API; this module is the single source of truth for that
resolution. Results are cached in DynamoDB so repeat calls are free.

Hard rules enforced here:
  1. NEVER hash, derive, or substring-match a UUID from an integer.
  2. NEVER use `LIKE '%integer_id%'` against a UUID column — UUIDs contain
     coincidental digit substrings.
  3. Every analytics query against migrated_data.* MUST resolve the integer
     to a real UUID first (or refuse).
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

from ..settings import get_aws_session, get_client, get_settings
from . import tool

GET_PATIENT_URL_ENV = "GET_PATIENT_URL"
PATIENT_RESOLVER_URL_ENV = "PATIENT_RESOLVER_URL"
INTERNAL_TOKEN_SECRET_ENV = "INTERNAL_TOKEN_SECRET_NAME"
PATIENT_RESOLVER_TOKEN_ENV = "PATIENT_RESOLVER_TOKEN_SECRET_NAME"
PATIENT_ID_MAP_TABLE_ENV = "PATIENT_ID_MAP_TABLE"
PATIENT_ID_UUID_MAP_TABLE_ENV = "PATIENT_ID_UUID_MAP_TABLE"

_TOKEN_CACHE: dict[str, str] = {}


def _get_internal_token() -> str:
    """Fetch the internal API token from Secrets Manager (cached in-process)."""
    secret_name = (
        os.environ.get(PATIENT_RESOLVER_TOKEN_ENV)
        or os.environ.get(INTERNAL_TOKEN_SECRET_ENV)
        or "INTERNAL_TOKEN"
    )
    if secret_name in _TOKEN_CACHE:
        return _TOKEN_CACHE[secret_name]
    sm = get_client("secretsmanager")
    resp = sm.get_secret_value(SecretId=secret_name)
    raw = resp.get("SecretString") or ""
    # The secret may be a bare string or a JSON blob; both are tolerated.
    raw_stripped = raw.strip()
    if raw_stripped.startswith("{"):
        try:
            d = json.loads(raw_stripped)
            value = d.get("INTERNAL_TOKEN") or d.get("internal_token") or d.get("token") or raw_stripped
        except json.JSONDecodeError:
            value = raw_stripped
    else:
        value = raw_stripped
    _TOKEN_CACHE[secret_name] = value
    return value


def _ddb_table():
    name = (
        os.environ.get(PATIENT_ID_UUID_MAP_TABLE_ENV)
        or os.environ.get(PATIENT_ID_MAP_TABLE_ENV)
    )
    if not name:
        return None
    return get_aws_session().resource("dynamodb").Table(name)


def _cache_get(patient_id: int) -> dict[str, Any] | None:
    table = _ddb_table()
    if table is None:
        return None
    try:
        resp = table.get_item(Key={"patient_id": int(patient_id)})
    except ClientError:
        return None
    return resp.get("Item")


def _cache_put(patient_id: int, payload: dict[str, Any]) -> None:
    table = _ddb_table()
    if table is None:
        return
    try:
        table.put_item(
            Item={
                "patient_id": int(patient_id),
                "pUuid": payload.get("pUuid"),
                "userId": payload.get("userId"),
                "raw_response": json.dumps(payload, default=str),
                "resolved_at": int(time.time()),
            }
        )
    except ClientError:
        # cache write is best-effort; never fails the resolution
        pass


def _call_get_patient_api(patient_id: int) -> dict[str, Any]:
    url = (
        os.environ.get(PATIENT_RESOLVER_URL_ENV)
        or os.environ.get(GET_PATIENT_URL_ENV)
        or get_settings().patient_resolver_url
    )
    if not url:
        raise RuntimeError(
            f"{PATIENT_RESOLVER_URL_ENV} or {GET_PATIENT_URL_ENV} env var not set. "
            "The agent cannot resolve integer patient_id → UUID without it."
        )
    token = _get_internal_token()
    # httpx is already in the deployment, but requests is part of awswrangler
    # layer too. Use httpx for consistency with the rest of the project.
    import httpx
    body = {"internal_token": token, "patient_id": int(patient_id)}
    with httpx.Client(timeout=float(get_settings().patient_resolver_timeout_s)) as c:
        resp = c.post(url, json=body)
    if resp.status_code != 200:
        raise RuntimeError(
            f"GET_PATIENT_URL returned HTTP {resp.status_code}: {resp.text[:300]}"
        )
    try:
        return resp.json()
    except ValueError as e:
        raise RuntimeError(f"GET_PATIENT_URL returned non-JSON: {resp.text[:300]}") from e


@tool(
    name="resolve_patient_uuid",
    description=(
        "Resolve an integer patient_id (e.g. 605) to its canonical pUuid "
        "(UUID used in migrated_data.* tables). REQUIRED before ANY Athena "
        "query that joins on the migrated `patient` UUID column. NEVER use "
        "LIKE '%605%' on a UUID — UUIDs contain coincidental digit "
        "substrings; the match is meaningless. Calls the internal Patients API "
        "(canonical source) and caches the result in DynamoDB so repeat lookups "
        "for the same patient_id return instantly."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "patient_id": {
                "type": "integer",
                "description": "Bare integer patient id, as it appears in S3 filenames.",
            },
            "force_refresh": {
                "type": "boolean",
                "default": False,
                "description": "Skip the cache and re-fetch from the Patients API.",
            },
        },
        "required": ["patient_id"],
    },
)
def resolve_patient_uuid(patient_id: int, force_refresh: bool = False) -> str:
    pid = int(patient_id)
    cached = None if force_refresh else _cache_get(pid)
    if cached and cached.get("pUuid"):
        return (
            f"patient_id={pid} (CACHED)\n"
            f"  pUuid:  {cached['pUuid']}\n"
            f"  userId: {cached.get('userId')}\n"
            f"  resolved_at: {cached.get('resolved_at')}"
        )
    try:
        data = _call_get_patient_api(pid)
    except Exception as e:  # noqa: BLE001 - surface to model
        return f"ERROR: could not resolve patient_id={pid}: {type(e).__name__}: {e}"
    p_uuid = data.get("pUuid") or data.get("patient_uuid")
    if not p_uuid:
        return (
            f"ERROR: API returned no pUuid for patient_id={pid}. "
            f"Raw response: {json.dumps(data)[:300]}"
        )
    _cache_put(pid, {**data, "pUuid": p_uuid})
    return (
        f"patient_id={pid} (FRESH from Patients API)\n"
        f"  pUuid:  {p_uuid}\n"
        f"  userId: {data.get('userId')}\n"
        f"  Use the pUuid in any migrated_data.* query as the `patient` column value."
    )


@tool(
    name="latest_data_date_for_patient",
    description=(
        "Return the most recent partition date that has data for a patient in "
        "`migrated_data.pc_timeseries` (the LIVE post-computation timeseries — "
        "the canonical source of truth for HR / Cardiolyse / per-sample "
        "analytics). Use this BEFORE assuming 'last 30 days' or 'recent'. "
        "PREFER passing `patient_id` (integer) — the tool resolves to the "
        "canonical UUID internally via the Patients API + DynamoDB cache, "
        "eliminating any risk of passing a wrong UUID. Pass `patient_uuid` "
        "only if you already obtained it via `resolve_patient_uuid`. "
        "(Note: do NOT use `pc_results_part` for recency — that table is "
        "frozen at 2025-07-07; `pc_timeseries` is updated daily.)"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "patient_id": {
                "type": "integer",
                "description": "Bare integer patient_id (preferred). Resolved to UUID internally.",
            },
            "patient_uuid": {
                "type": "string",
                "description": "Patient UUID — only if you already have a verified one.",
            },
        },
    },
)
def latest_data_date_for_patient(
    patient_id: int | None = None,
    patient_uuid: str | None = None,
) -> str:
    if patient_id is None and not patient_uuid:
        return "ERROR: must provide either patient_id (preferred) or patient_uuid."
    if patient_uuid is None:
        # Resolve internally — cache hit if we've seen this id before.
        cached = _cache_get(int(patient_id))
        if cached and cached.get("pUuid"):
            patient_uuid = cached["pUuid"]
        else:
            try:
                data = _call_get_patient_api(int(patient_id))
            except Exception as e:  # noqa: BLE001
                return f"ERROR: could not resolve patient_id={patient_id}: {type(e).__name__}: {e}"
            patient_uuid = data.get("pUuid") or data.get("patient_uuid")
            if not patient_uuid:
                return f"ERROR: API returned no pUuid for patient_id={patient_id}"
            _cache_put(int(patient_id), {**data, "pUuid": patient_uuid})
    s = get_settings()
    if "-" not in patient_uuid:
        return f"ERROR: invalid UUID {patient_uuid!r}"
    # Query the LIVE pc_timeseries — pc_results_part has been frozen since
    # 2025-07-07 and would mislead the agent into reporting year-old data
    # as "recent". pc_timeseries is updated within ~24h of upload.
    sql = (
        "SELECT MAX(date) AS latest_date, COUNT(DISTINCT date) AS distinct_days "
        "FROM migrated_data.pc_timeseries "
        f"WHERE patient = '{patient_uuid}'"
    )
    athena = get_client("athena")
    resp = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": s.athena_default_database},
        WorkGroup=s.athena_workgroup,
        ResultConfiguration={
            "OutputLocation": f"s3://{s.athena_results_bucket}/" if s.athena_results_bucket else None
        }
        if s.athena_results_bucket
        else {},
    )
    qid = resp["QueryExecutionId"]
    deadline = time.time() + 30
    while time.time() < deadline:
        info = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
        state = info["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            return f"ERROR: query {qid} ended in {state}: {info['Status'].get('StateChangeReason')}"
        time.sleep(1)
    else:
        return f"ERROR: query {qid} timed out"
    rows = athena.get_query_results(QueryExecutionId=qid)["ResultSet"]["Rows"]
    if len(rows) < 2:
        return f"No rows in pc_timeseries for patient_uuid={patient_uuid}."
    cells = [c.get("VarCharValue", "") for c in rows[1].get("Data", [])]
    latest, days_count = cells + [""] * (2 - len(cells))
    total = days_count  # backwards-compat output formatting
    scanned = info["Statistics"].get("DataScannedInBytes", 0)

    # Compute migration-lag age. If the latest migrated date is much older
    # than "today", the model must be told explicitly so it doesn't silently
    # substitute year-old data for "last month".
    age_str = ""
    pid_str = f" patient_id={patient_id}" if patient_id is not None else ""
    if latest and latest != "(none)":
        from datetime import datetime, timezone
        try:
            latest_dt = datetime.strptime(latest, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            today = datetime.now(timezone.utc)
            age_days = (today - latest_dt).days
            severity = ""
            if age_days > 14:
                severity = (
                    f"\n⚠️  WARNING: latest pc_timeseries date is {age_days} days "
                    f"BEHIND today ({today.date().isoformat()}). Typical lag for "
                    f"pc_timeseries is 1-3 days. Mention this gap explicitly to "
                    f"the user and slide the analytics window back to {latest}."
                )
            elif age_days > 3:
                severity = (
                    f"\nNOTE: latest pc_timeseries date is {age_days} days behind "
                    f"today (typical is 1-3 days). Acceptable but worth mentioning."
                )
            age_str = f" (age={age_days} days vs today {today.date().isoformat()}){severity}"
        except ValueError:
            pass

    return (
        f"latest_date={latest or '(none)'}, distinct_days={days_count} "
        f"in migrated_data.pc_timeseries for patient={patient_uuid}{pid_str}. "
        f"Athena scanned_bytes={scanned}.{age_str}"
    )
