"""Core domain models for OpsCommander.

These are plain dataclasses with no third-party dependencies so the incident
engine can run and be tested without FastAPI, boto3, or the Anthropic SDK
installed. The API layer maps these to/from its own pydantic schemas.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _now() -> str:
    """UTC timestamp in ISO-8601 with a trailing Z."""
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Severity(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    INFO = "Info"

    @property
    def rank(self) -> int:
        order = {
            Severity.CRITICAL: 4,
            Severity.HIGH: 3,
            Severity.MEDIUM: 2,
            Severity.LOW: 1,
            Severity.INFO: 0,
        }
        return order[self]


class IncidentStatus(str, Enum):
    DETECTED = "Detected"
    ANALYZING = "Analyzing"
    AWAITING_APPROVAL = "AwaitingApproval"
    REMEDIATING = "Remediating"
    RESOLVED = "Resolved"
    ESCALATED = "Escalated"
    FAILED = "Failed"


class Stage(str, Enum):
    """Pipeline stages, one per agent."""

    DETECTION = "detection"
    LOG_ANALYSIS = "log_analysis"
    INFRASTRUCTURE = "infrastructure"
    RECOMMENDATION = "recommendation"
    APPROVAL = "approval"
    REMEDIATION = "remediation"
    REPORTING = "reporting"


@dataclass
class TimelineEntry:
    """A single audited event in the incident lifecycle."""

    timestamp: str
    stage: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentResult:
    """The structured output of a single agent."""

    agent: str
    ok: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=_now)
    finished_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Recommendation:
    """A single fix recommendation produced by the Recommendation Agent."""

    title: str
    rationale: str
    action: str  # machine-readable action key, e.g. "restart_lambda"
    confidence: float = 0.5
    references: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ApprovalDecision:
    """The Approval Agent's ruling on a proposed remediation."""

    action: str
    approved: bool
    auto: bool  # True when decided by policy, False when it needs a human
    reason: str
    risk: str  # "safe" | "risky" | "destructive"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RemediationResult:
    """The outcome of executing (or attempting) a remediation action."""

    action: str
    executed: bool
    success: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Incident:
    """The incident being worked, plus the accumulated state of the pipeline.

    A single object threads through every agent. Each agent reads what it needs
    and writes its result back, so the object is the full audit record by the
    time the Reporting Agent runs.
    """

    id: str = field(default_factory=lambda: new_id("inc"))
    service: str = "unknown"
    alarm: str = "unknown"
    title: str = ""
    severity: Severity = Severity.MEDIUM
    status: IncidentStatus = IncidentStatus.DETECTED
    root_cause: str | None = None

    # Raw signals that triggered the incident.
    source_event: dict[str, Any] = field(default_factory=dict)

    # Per-agent outputs.
    agent_results: dict[str, AgentResult] = field(default_factory=dict)
    recommendations: list[Recommendation] = field(default_factory=list)
    approval: ApprovalDecision | None = None
    remediation: RemediationResult | None = None

    # Cross-cutting.
    timeline: list[TimelineEntry] = field(default_factory=list)
    report_uri: str | None = None

    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    # ------------------------------------------------------------------ #
    # Mutation helpers
    # ------------------------------------------------------------------ #
    def log(self, stage: str, message: str, **detail: Any) -> None:
        self.timeline.append(
            TimelineEntry(timestamp=_now(), stage=stage, message=message, detail=detail)
        )
        self.updated_at = _now()

    def record(self, result: AgentResult) -> None:
        self.agent_results[result.agent] = result
        self.updated_at = _now()

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "service": self.service,
            "alarm": self.alarm,
            "title": self.title,
            "severity": self.severity.value,
            "status": self.status.value,
            "root_cause": self.root_cause,
            "source_event": self.source_event,
            "agent_results": {k: v.to_dict() for k, v in self.agent_results.items()},
            "recommendations": [r.to_dict() for r in self.recommendations],
            "approval": self.approval.to_dict() if self.approval else None,
            "remediation": self.remediation.to_dict() if self.remediation else None,
            "timeline": [t.to_dict() for t in self.timeline],
            "report_uri": self.report_uri,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Incident":
        inc = cls(
            id=d["id"],
            service=d.get("service", "unknown"),
            alarm=d.get("alarm", "unknown"),
            title=d.get("title", ""),
            severity=Severity(d.get("severity", "Medium")),
            status=IncidentStatus(d.get("status", "Detected")),
            root_cause=d.get("root_cause"),
            source_event=d.get("source_event", {}),
            report_uri=d.get("report_uri"),
            created_at=d.get("created_at", _now()),
            updated_at=d.get("updated_at", _now()),
        )
        inc.agent_results = {
            k: AgentResult(**v) for k, v in d.get("agent_results", {}).items()
        }
        inc.recommendations = [Recommendation(**r) for r in d.get("recommendations", [])]
        if d.get("approval"):
            inc.approval = ApprovalDecision(**d["approval"])
        if d.get("remediation"):
            inc.remediation = RemediationResult(**d["remediation"])
        inc.timeline = [TimelineEntry(**t) for t in d.get("timeline", [])]
        return inc
