"""The multi-agent orchestrator.

Runs the seven agents in sequence over a single ``Incident`` object, persisting
after every stage so the incident is inspectable mid-flight and recoverable if
a stage fails. The Approval Agent acts as a gate: when it does not auto-approve,
the pipeline halts before remediation and the incident is left awaiting a human.
Calling :meth:`resume_after_approval` continues from remediation once a human
approves.
"""

from __future__ import annotations

from .agents import (
    ApprovalAgent,
    IncidentDetectionAgent,
    InfrastructureAgent,
    LogAnalysisAgent,
    RecommendationAgent,
    RemediationAgent,
    ReportingAgent,
)
from .config import Settings, get_settings
from .logging_config import get_logger
from .models import Incident, IncidentStatus, Severity
from .storage import IncidentRepository, get_repository

log = get_logger("orchestrator")


class Orchestrator:
    def __init__(
        self,
        settings: Settings | None = None,
        repository: IncidentRepository | None = None,
    ):
        self.settings = settings or get_settings()
        self.repo = repository or get_repository(self.settings)

        # Agents that always run, in order, before the approval gate.
        self.detection = IncidentDetectionAgent(self.settings)
        self.log_analysis = LogAnalysisAgent(self.settings)
        self.infrastructure = InfrastructureAgent(self.settings)
        self.recommendation = RecommendationAgent(self.settings)
        self.approval = ApprovalAgent(self.settings)
        self.remediation = RemediationAgent(self.settings)
        self.reporting = ReportingAgent(self.settings)

    # ------------------------------------------------------------------ #
    def handle_incident(
        self,
        service: str,
        alarm: str,
        severity: str | None = None,
        source_event: dict | None = None,
    ) -> Incident:
        """Create and run an incident end-to-end (up to the approval gate)."""
        incident = Incident(
            service=service,
            alarm=alarm,
            source_event=source_event or {},
        )
        if severity:
            try:
                incident.severity = Severity(severity)
            except ValueError:
                log.warning("Unknown severity '%s'; will auto-score", severity)
        self.repo.save(incident)
        return self.run(incident)

    def run(self, incident: Incident) -> Incident:
        """Run the diagnostic + decision agents, then remediation if approved."""
        for agent in (
            self.detection,
            self.log_analysis,
            self.infrastructure,
            self.recommendation,
            self.approval,
        ):
            self._run_agent(agent, incident)

        approved = incident.approval is not None and incident.approval.approved
        if approved:
            self._run_agent(self.remediation, incident)
        else:
            log.info(
                "Incident %s halted at approval gate (%s)",
                incident.id,
                incident.status.value,
            )

        self._run_agent(self.reporting, incident)
        self.repo.save(incident)
        return incident

    # ------------------------------------------------------------------ #
    def resume_after_approval(self, incident_id: str, approved_by: str) -> Incident | None:
        """Continue a halted incident once a human has approved remediation."""
        incident = self.repo.get(incident_id)
        if incident is None:
            return None
        if incident.approval is None:
            log.warning("Incident %s has no pending approval", incident_id)
            return incident

        # Record the human decision, then run remediation + a fresh report.
        incident.approval.approved = True
        incident.approval.auto = False
        incident.approval.reason += f" | Manually approved by {approved_by}."
        incident.status = IncidentStatus.REMEDIATING
        incident.log("approval", f"Manually approved by {approved_by}")

        self._run_agent(self.remediation, incident)
        self._run_agent(self.reporting, incident)
        self.repo.save(incident)
        return incident

    # ------------------------------------------------------------------ #
    def _run_agent(self, agent, incident: Incident) -> None:
        try:
            result = agent.run(incident)
            incident.record(result)
        except Exception as exc:  # noqa: BLE001 - one bad agent shouldn't crash the run
            log.exception("Agent '%s' failed", agent.name)
            incident.log(agent.name, f"Agent failed: {exc}")
            incident.status = IncidentStatus.FAILED
        finally:
            self.repo.save(incident)
