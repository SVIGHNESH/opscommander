"""Runtime configuration, resolved from environment variables.

Everything has a sensible default so the system runs locally with zero setup.
Set OPSCOMMANDER_MODE=aws (and provide AWS credentials) to talk to real
services; the default MODE=mock uses in-repo fakes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _get(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _get_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    # "mock" runs everything against local fakes; "aws" uses boto3/Bedrock.
    mode: str = _get("OPSCOMMANDER_MODE", "mock")

    aws_region: str = _get("AWS_REGION", "us-east-1")

    # Bedrock model id. On Bedrock the Anthropic model id carries an
    # "anthropic." prefix (e.g. anthropic.claude-opus-4-8).
    bedrock_model_id: str = _get("OPSCOMMANDER_BEDROCK_MODEL", "anthropic.claude-opus-4-8")
    bedrock_effort: str = _get("OPSCOMMANDER_BEDROCK_EFFORT", "high")
    bedrock_max_tokens: int = int(_get("OPSCOMMANDER_BEDROCK_MAX_TOKENS", "2048"))

    # Persistence.
    dynamo_table: str = _get("OPSCOMMANDER_DDB_TABLE", "opscommander-incidents")
    s3_bucket: str = _get("OPSCOMMANDER_S3_BUCKET", "opscommander-reports")
    local_store_dir: str = _get(
        "OPSCOMMANDER_DATA_DIR",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data"),
    )

    # Notifications.
    sns_topic_arn: str = _get("OPSCOMMANDER_SNS_TOPIC_ARN", "")
    slack_webhook_url: str = _get("OPSCOMMANDER_SLACK_WEBHOOK", "")

    # Approval policy. Actions at/above this severity that are only "safe" are
    # auto-approved; anything "risky"/"destructive" always escalates.
    auto_approve_max_severity: str = _get("OPSCOMMANDER_AUTO_APPROVE_SEVERITY", "High")

    @property
    def is_mock(self) -> bool:
        return self.mode.strip().lower() != "aws"


def get_settings() -> Settings:
    """Fresh Settings read from the current environment (cheap; not cached so
    tests can monkeypatch env vars between calls)."""
    return Settings()
