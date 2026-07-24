"""Approval Agent.

The safety gate. It classifies the top recommended action's risk and decides
whether automated remediation may proceed, or whether a human must approve.
Destructive actions (delete database, terminate EC2, ...) always escalate.
"""

from __future__ import annotations

from ..models import (
    AgentResult,
    ApprovalDecision,
    Incident,
    IncidentStatus,
    Severity,
    _now,
)
from .base import Agent

# Risk classification of every known action.
SAFE_ACTIONS = {
    "restart_lambda",
    "increase_lambda_timeout",
    "clear_failed_jobs",
    "restart_ecs_task",
    "increase_db_connections",
}
RISKY_ACTIONS = {
    "scale_asg",
    "trigger_deployment",
    "rotate_credentials",
}
DESTRUCTIVE_ACTIONS = {
    "delete_database",
    "terminate_ec2",
    "drop_table",
    "delete_stack",
    "wipe_cache",
}


class ApprovalAgent(Agent):
    name = "approval"

    def run(self, incident: Incident) -> AgentResult:
        started = _now()

        if not incident.recommendations:
            decision = ApprovalDecision(
                action="manual_investigation",
                approved=False,
                auto=False,
                reason="No actionable recommendation was produced.",
                risk="safe",
            )
            incident.approval = decision
            incident.status = IncidentStatus.ESCALATED
            incident.log(self.name, "No recommendation to approve; escalating.")
            return self._result(
                False, "Escalated: no recommendation", started, **decision.to_dict()
            )

        action = incident.recommendations[0].action
        risk = self._risk(action)
        decision = self._decide(action, risk, incident.severity)
        incident.approval = decision

        if decision.approved:
            incident.status = IncidentStatus.REMEDIATING
        else:
            incident.status = IncidentStatus.AWAITING_APPROVAL

        incident.log(
            self.name,
            f"Action '{action}' classified {risk}; "
            f"{'auto-approved' if decision.approved else 'needs manual approval'}",
        )
        return self._result(
            decision.approved,
            decision.reason,
            started,
            **decision.to_dict(),
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _risk(action: str) -> str:
        if action in DESTRUCTIVE_ACTIONS:
            return "destructive"
        if action in RISKY_ACTIONS:
            return "risky"
        if action in SAFE_ACTIONS:
            return "safe"
        # Unknown actions (incl. manual_investigation) are treated cautiously.
        return "risky"

    def _decide(
        self, action: str, risk: str, severity: Severity
    ) -> ApprovalDecision:
        if risk == "destructive":
            return ApprovalDecision(
                action=action,
                approved=False,
                auto=False,
                reason=f"'{action}' is destructive and always requires human approval.",
                risk=risk,
            )
        if risk == "risky":
            return ApprovalDecision(
                action=action,
                approved=False,
                auto=False,
                reason=f"'{action}' carries production risk; escalating for approval.",
                risk=risk,
            )

        # Safe action: auto-approve only within the configured severity ceiling.
        ceiling = Severity(self.settings.auto_approve_max_severity)
        if severity.rank <= ceiling.rank:
            return ApprovalDecision(
                action=action,
                approved=True,
                auto=True,
                reason=f"'{action}' is safe and severity {severity.value} is within "
                f"the auto-approval ceiling ({ceiling.value}).",
                risk=risk,
            )
        return ApprovalDecision(
            action=action,
            approved=False,
            auto=False,
            reason=f"'{action}' is safe but severity {severity.value} exceeds the "
            f"auto-approval ceiling ({ceiling.value}); escalating.",
            risk=risk,
        )
