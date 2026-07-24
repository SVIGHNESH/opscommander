"""Local JSON-file incident store — the default (mock-mode) backend.

One file per incident under ``settings.local_store_dir``. Simple, inspectable,
and dependency-free; good enough for local development and demos.
"""

from __future__ import annotations

import json
import os
import tempfile

from ..config import Settings, get_settings
from ..logging_config import get_logger
from ..models import Incident
from .repository import IncidentRepository

log = get_logger("storage.local")


class LocalFileRepository(IncidentRepository):
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.dir = os.path.join(self.settings.local_store_dir, "incidents")
        os.makedirs(self.dir, exist_ok=True)

    def _path(self, incident_id: str) -> str:
        return os.path.join(self.dir, f"{incident_id}.json")

    def save(self, incident: Incident) -> None:
        path = self._path(incident.id)
        # Atomic write so a concurrent reader never sees a half-written file.
        fd, tmp = tempfile.mkstemp(dir=self.dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(incident.to_dict(), fh, indent=2, default=str)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def get(self, incident_id: str) -> Incident | None:
        path = self._path(incident_id)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as fh:
            return Incident.from_dict(json.load(fh))

    def list(self, limit: int = 50) -> list[Incident]:
        files = [
            os.path.join(self.dir, f)
            for f in os.listdir(self.dir)
            if f.endswith(".json")
        ]
        files.sort(key=os.path.getmtime, reverse=True)
        out: list[Incident] = []
        for path in files[:limit]:
            try:
                with open(path, encoding="utf-8") as fh:
                    out.append(Incident.from_dict(json.load(fh)))
            except Exception as exc:  # noqa: BLE001
                log.warning("Skipping unreadable incident file %s: %s", path, exc)
        return out
