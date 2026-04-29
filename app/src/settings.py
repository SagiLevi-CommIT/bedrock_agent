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

    bedrock_model_id: str = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
    bedrock_max_tokens: int = 4096

    athena_workgroup: str = "primary"
    athena_default_database: str = "migrated_data"
    athena_max_rows: int = 1000

    sessions_table: str = "agent-staging-sessions"
    cost_table: str = "agent-staging-cost-rollup"
    output_bucket: str | None = None

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
