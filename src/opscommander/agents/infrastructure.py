"""Infrastructure Agent.

Reviews the health of the resources behind the affected service (Lambda, API
Gateway, EC2, ECS) so the Recommendation and Approval agents can reason about
current state rather than the alarm alone.
"""

from __future__ import annotations

from ..aws.infra import InfrastructureAdapter
from ..models import AgentResult, Incident, _now
from .base import Agent


class InfrastructureAgent(Agent):
    name = "infrastructure"

    def __init__(self, settings=None, infra: InfrastructureAdapter | None = None):
        super().__init__(settings)
        self.infra = infra or InfrastructureAdapter(self.settings)

    def run(self, incident: Incident) -> AgentResult:
        started = _now()
        health = self.infra.check_health(incident.service, incident.alarm)
        unhealthy = self._summarise_unhealthy(health)

        incident.log(
            self.name,
            f"Infrastructure review complete; {len(unhealthy)} component(s) degraded",
            unhealthy=unhealthy,
        )
        return self._result(
            ok=True,
            summary=(
                "All components healthy"
                if not unhealthy
                else f"Degraded: {', '.join(unhealthy)}"
            ),
            started_at=started,
            health=health,
            unhealthy=unhealthy,
        )

    @staticmethod
    def _summarise_unhealthy(health: dict) -> list[str]:
        out: list[str] = []
        for component, state in health.items():
            if not isinstance(state, dict):
                continue
            if state.get("healthy") is False:
                out.append(component)
            elif state.get("unhealthy"):
                out.append(component)
            elif state.get("pending_tasks"):
                out.append(component)
        return out
