"""boto3 client factory with graceful degradation.

If boto3 isn't installed, or credentials/region aren't configured, callers get
``None`` and are expected to fall back to their mock behaviour. Nothing here
raises on the happy "no AWS available" path.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from ..config import Settings, get_settings
from ..logging_config import get_logger

log = get_logger("aws.clients")


@lru_cache(maxsize=1)
def _boto3():
    try:
        import boto3  # type: ignore

        return boto3
    except ImportError:
        return None


def boto3_available() -> bool:
    return _boto3() is not None


def make_client(service: str, settings: Settings | None = None) -> Any | None:
    """Return a boto3 client for ``service`` or ``None`` if unavailable."""
    settings = settings or get_settings()
    if settings.is_mock:
        return None
    boto3 = _boto3()
    if boto3 is None:
        log.warning("boto3 not installed; %s client unavailable", service)
        return None
    try:
        return boto3.client(service, region_name=settings.aws_region)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not create %s client: %s", service, exc)
        return None
