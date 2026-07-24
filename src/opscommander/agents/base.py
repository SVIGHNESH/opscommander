"""Base class shared by every agent.

Each agent has a stable ``name``, and a ``run(incident) -> AgentResult`` method
that reads whatever it needs off the incident and writes its structured result
back. The orchestrator owns sequencing; agents own their single concern.
"""

from __future__ import annotations

import abc

from ..config import Settings, get_settings
from ..logging_config import get_logger
from ..models import AgentResult, Incident, _now


class Agent(abc.ABC):
    #: Stable identifier, also the key under which results are stored.
    name: str = "agent"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.log = get_logger(f"agent.{self.name}")

    @abc.abstractmethod
    def run(self, incident: Incident) -> AgentResult:  # pragma: no cover - abstract
        ...

    # Convenience for subclasses to build a result with consistent timestamps.
    def _result(
        self, ok: bool, summary: str, started_at: str, **data: object
    ) -> AgentResult:
        return AgentResult(
            agent=self.name,
            ok=ok,
            summary=summary,
            data=dict(data),
            started_at=started_at,
            finished_at=_now(),
        )
