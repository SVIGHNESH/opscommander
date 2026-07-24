"""Incident Detection Agent.

Normalises the incoming CloudWatch alarm / event into a titled, severity-scored
incident and pulls the initial metric snapshot. It is the entry point of the
pipeline.
"""

from __future__ import annotations

from ..aws.cloudwatch import CloudWatchAdapter
from ..models import AgentResult, Incident, IncidentStatus, Severity, _now
from .base import Agent


class IncidentDetectionAgent(Agent):
    name = "detection"

    def __init__(self, settings=None, cloudwatch: CloudWatchAdapter | None = None):
        super().__init__(settings)
        self.cw = cloudwatch or CloudWatchAdapter(self.settings)

    def run(self, incident: Incident) -> AgentResult:
        started = _now()
        incident.status = IncidentStatus.DETECTED

        # Detection can only raise severity, never lower an explicitly-provided
        # one - we keep the more severe of the caller's value and the inferred.
        inferred = self._score_severity(incident.alarm, incident.service)
        severity = max(incident.severity, inferred, key=lambda s: s.rank)
        incident.severity = severity
        if not incident.title:
            incident.title = self._title(incident.alarm, incident.service)

        metrics = self.cw.fetch_metrics(incident.service, incident.alarm)

        incident.log(
            self.name,
            f"Detected '{incident.title}' on {incident.service} "
            f"(severity={severity.value})",
            metrics=metrics,
        )
        return self._result(
            ok=True,
            summary=f"{incident.title} [{severity.value}]",
            started_at=started,
            severity=severity.value,
            metrics=metrics,
            affected_service=incident.service,
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _score_severity(alarm: str, service: str) -> Severity:
        a = alarm.lower()
        if any(k in a for k in ("outage", "down", "5xx", "oom", "memory", "data loss")):
            return Severity.CRITICAL
        if any(k in a for k in ("timeout", "cpu", "error", "throttle", "latency")):
            return Severity.HIGH
        if any(k in a for k in ("warning", "degraded", "slow")):
            return Severity.MEDIUM
        return Severity.LOW

    @staticmethod
    def _title(alarm: str, service: str) -> str:
        return f"{service} {alarm}".strip().title()
