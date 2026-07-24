"""DynamoDB incident store (used when OPSCOMMANDER_MODE=aws).

The whole incident document is stored as a single JSON attribute keyed by
``id``. That keeps the table schema trivial while still allowing point reads
and a bounded scan for listing. Construction raises if boto3 is unavailable so
the storage factory can fall back to the local store.
"""

from __future__ import annotations

import json

from ..config import Settings, get_settings
from ..logging_config import get_logger
from ..models import Incident
from .repository import IncidentRepository

log = get_logger("storage.dynamo")


class DynamoIncidentRepository(IncidentRepository):
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        import boto3  # raises ImportError -> factory falls back

        self._table = boto3.resource(
            "dynamodb", region_name=self.settings.aws_region
        ).Table(self.settings.dynamo_table)

    def save(self, incident: Incident) -> None:
        self._table.put_item(
            Item={
                "id": incident.id,
                "status": incident.status.value,
                "severity": incident.severity.value,
                "service": incident.service,
                "created_at": incident.created_at,
                "updated_at": incident.updated_at,
                "document": json.dumps(incident.to_dict(), default=str),
            }
        )

    def get(self, incident_id: str) -> Incident | None:
        resp = self._table.get_item(Key={"id": incident_id})
        item = resp.get("Item")
        if not item:
            return None
        return Incident.from_dict(json.loads(item["document"]))

    def list(self, limit: int = 50) -> list[Incident]:
        resp = self._table.scan(Limit=limit)
        incidents = [
            Incident.from_dict(json.loads(i["document"]))
            for i in resp.get("Items", [])
            if "document" in i
        ]
        incidents.sort(key=lambda i: i.created_at, reverse=True)
        return incidents
