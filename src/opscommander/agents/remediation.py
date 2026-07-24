"""Remediation Agent.

Executes the approved action through the infrastructure adapter. If approval
was not granted, it records that remediation was skipped and leaves the
incident awaiting a human. It never executes an unapproved action.
"""

from __future__ import annotations

from ..aws.infra import InfrastructureAdapter
from ..models import (
    AgentResult,
    Incident,
    IncidentStatus,
    RemediationResult,
    _now,
)
from .base import Agent


class RemediationAgent(Agent):
    name = "remediation"

    def __init__(self, settings=None, infra: InfrastructureAdapter | None = None):
        super().__init__(settings)
        self.infra = infra or InfrastructureAdapter(self.settings)

    def run(self, incident: Incident) -> AgentResult:
        started = _now()
        approval = incident.approval

        if approval is None or not approval.approved:
            result = RemediationResult(
                action=approval.action if approval else "none",
                executed=False,
                success=False,
                detail="Remediation skipped: action not approved for automated execution.",
            )
            incident.remediation = result
            incident.log(self.name, result.detail)
            return self._result(False, result.detail, started, **result.to_dict())

        success, detail = self.infra.execute(approval.action, incident.service)
        result = RemediationResult(
            action=approval.action,
            executed=True,
            success=success,
            detail=detail,
        )
        incident.remediation = result
        incident.status = (
            IncidentStatus.RESOLVED if success else IncidentStatus.FAILED
        )
        incident.log(
            self.name,
            f"Executed '{approval.action}': {'success' if success else 'failed'} - {detail}",
        )
        return self._result(success, detail, started, **result.to_dict())
