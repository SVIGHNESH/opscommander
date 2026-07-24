"""Reporting Agent.

Compiles the incident summary, root-cause analysis, timeline, resolution steps
and recommendations into a report (JSON + Markdown, PDF when reportlab is
available), persists it, and fires notifications.
"""

from __future__ import annotations

from ..aws.notifications import Notifier
from ..models import AgentResult, Incident, IncidentStatus, _now
from ..reporting.report_builder import ReportBuilder
from .base import Agent


class ReportingAgent(Agent):
    name = "reporting"

    def __init__(
        self,
        settings=None,
        builder: ReportBuilder | None = None,
        notifier: Notifier | None = None,
    ):
        super().__init__(settings)
        self.builder = builder or ReportBuilder(self.settings)
        self.notifier = notifier or Notifier(self.settings)

    def run(self, incident: Incident) -> AgentResult:
        started = _now()
        artifacts = self.builder.build(incident)
        incident.report_uri = artifacts.get("json")

        subject = f"[{incident.severity.value}] {incident.title} - {incident.status.value}"
        self.notifier.notify(subject, self._notification_body(incident))

        incident.log(
            self.name,
            f"Report generated ({', '.join(artifacts)}) and notifications sent",
            artifacts=artifacts,
        )
        return self._result(
            True,
            f"Report written: {', '.join(artifacts.values())}",
            started,
            artifacts=artifacts,
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _notification_body(incident: Incident) -> str:
        action = incident.remediation.action if incident.remediation else "n/a"
        taken = (
            incident.remediation.detail
            if incident.remediation and incident.remediation.executed
            else "No automated action taken"
        )
        lines = [
            f"Incident: {incident.title}",
            f"Service:  {incident.service}",
            f"Severity: {incident.severity.value}",
            f"Status:   {incident.status.value}",
            f"Root cause: {incident.root_cause or 'undetermined'}",
            f"Action:   {action}",
            f"Outcome:  {taken}",
        ]
        if incident.status in (IncidentStatus.AWAITING_APPROVAL, IncidentStatus.ESCALATED):
            lines.append(f"⚠ Awaiting human approval - POST /approve with id={incident.id}")
        return "\n".join(lines)
