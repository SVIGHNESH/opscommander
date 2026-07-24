"""Log Analysis Agent.

Pulls recent logs, extracts exceptions/errors, and infers a likely root cause
with simple, explainable pattern matching. The inferred root cause is written
onto the incident for downstream agents.
"""

from __future__ import annotations

import re

from ..aws.cloudwatch import CloudWatchAdapter
from ..models import AgentResult, Incident, IncidentStatus, _now
from .base import Agent

_ERROR_RE = re.compile(r"\b(ERROR|FATAL|Exception|OutOfMemory|timed out|timeout)\b", re.I)

# Ordered most-specific first; first match wins.
_ROOT_CAUSE_RULES: list[tuple[str, str]] = [
    (r"database.*(timeout|could not connect)|OperationalError|connection pool",
     "Database connection timeout"),
    (r"out ?of ?memory|OutOfMemoryError|signal: killed|OOM", "Out-of-memory (OOM) kill"),
    (r"task timed out|timed out after", "Function execution timeout"),
    (r"502|503|bad gateway|circuit breaker", "Downstream dependency failure (5xx)"),
    (r"NullPointerException|unhandled exception", "Unhandled application exception"),
    (r"CPUUtilization|high cpu", "CPU saturation"),
]


class LogAnalysisAgent(Agent):
    name = "log_analysis"

    def __init__(self, settings=None, cloudwatch: CloudWatchAdapter | None = None):
        super().__init__(settings)
        self.cw = cloudwatch or CloudWatchAdapter(self.settings)

    def run(self, incident: Incident) -> AgentResult:
        started = _now()
        incident.status = IncidentStatus.ANALYZING

        logs = self.cw.fetch_logs(incident.service, incident.alarm)
        errors = [ln for ln in logs if _ERROR_RE.search(ln)]
        root_cause = self._infer_root_cause(logs) or "Undetermined"
        incident.root_cause = root_cause

        incident.log(
            self.name,
            f"Analysed {len(logs)} log lines, {len(errors)} error(s); "
            f"root cause: {root_cause}",
            error_count=len(errors),
        )
        return self._result(
            ok=root_cause != "Undetermined",
            summary=f"Root cause: {root_cause}",
            started_at=started,
            root_cause=root_cause,
            error_lines=errors[:10],
            sampled_logs=logs[:10],
        )

    @staticmethod
    def _infer_root_cause(logs: list[str]) -> str | None:
        blob = "\n".join(logs)
        for pattern, cause in _ROOT_CAUSE_RULES:
            if re.search(pattern, blob, re.I):
                return cause
        return None
