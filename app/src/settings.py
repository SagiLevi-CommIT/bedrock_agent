"""Runtime settings, ported from claude_aws_agent/tools/config.py.

Env-driven; works with task-role IAM in production and an AWS_PROFILE locally.
"""
from __future__ import annotations

from functools import lru_cache

import boto3
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    aws_region: str = "eu-central-1"
    aws_profile: str | None = None

    # Default kept as the desired Claude model so anyone running locally with
    # the right SCP gets the right behavior. Production env var overrides
    # this until the org SCP is updated to permit Anthropic.
    bedrock_model_id: str = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
    bedrock_fast_model_id: str = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    bedrock_max_tokens: int = 4096

    athena_workgroup: str = "primary"
    athena_default_database: str = "migrated_data"
    athena_max_rows: int = 1000
    athena_results_bucket: str | None = None
    athena_max_scan_gb_default: float = 1.0
    athena_cost_per_tb_usd: float = 5.0

    sessions_table: str = "claude-aws-agent-staging-sessions"
    cost_table: str = "claude-aws-agent-staging-cost"
    output_bucket: str | None = None

    advice_prefix: str = "advice/raw"
    playbooks_dir: str = "/app/knowledge/playbooks"
    lessons_curated_path: str = "/app/knowledge/lessons/curated.md"

    events_bucket: str | None = None
    event_sessions_table: str = "migrated_data.event_sessions"

    patient_id_uuid_map_table: str | None = None
    patient_resolver_url: str | None = None
    patient_resolver_token_secret_name: str | None = None
    patient_resolver_timeout_s: int = 10

    # Deterministic Tool API (the S3 data/visualization tool's HTTP surface,
    # reached over the shared ALB / internal network). The agent calls it via
    # httpx (see tools/tool_api_client.py); it owns fetch/coverage/visualize.
    tool_api_base_url: str | None = None
    tool_api_token: str | None = None  # direct bearer for local/dev
    tool_api_token_secret_name: str | None = None  # Secrets Manager name in prod
    tool_api_timeout_s: int = 30
    # Path the chat UI links to when offering "open the data tool" preloaded.
    tool_ui_base_path: str = "/tool-ui"

    log_level: str = "INFO"
    allow_writes: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def get_aws_session() -> boto3.Session:
    s = get_settings()
    kwargs: dict[str, str] = {"region_name": s.aws_region}
    if s.aws_profile:
        kwargs["profile_name"] = s.aws_profile
    return boto3.Session(**kwargs)


def get_client(service: str):
    return get_aws_session().client(service)
