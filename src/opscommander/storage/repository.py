"""Repository interface for incident persistence."""

from __future__ import annotations

import abc

from ..models import Incident


class IncidentRepository(abc.ABC):
    @abc.abstractmethod
    def save(self, incident: Incident) -> None: ...

    @abc.abstractmethod
    def get(self, incident_id: str) -> Incident | None: ...

    @abc.abstractmethod
    def list(self, limit: int = 50) -> list[Incident]: ...
