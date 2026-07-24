"""Incident persistence with a DynamoDB backend and a local-file fallback."""

from __future__ import annotations

from ..config import Settings, get_settings
from ..logging_config import get_logger
from .local_repo import LocalFileRepository
from .repository import IncidentRepository

log = get_logger("storage")


def get_repository(settings: Settings | None = None) -> IncidentRepository:
    settings = settings or get_settings()
    if not settings.is_mock:
        try:
            from .dynamo_repo import DynamoIncidentRepository

            return DynamoIncidentRepository(settings)
        except Exception as exc:  # noqa: BLE001 - fall back gracefully
            log.warning("DynamoDB unavailable (%s); using local file store", exc)
    return LocalFileRepository(settings)


__all__ = ["get_repository", "IncidentRepository", "LocalFileRepository"]
