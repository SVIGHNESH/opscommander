"""Run a set of demo incidents through the pipeline and print a summary.

Usage:  python scripts/seed_incident.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from opscommander.orchestrator import Orchestrator  # noqa: E402

SCENARIOS = [
    ("orders-api", "Database Timeout", "High"),      # safe action -> auto-remediated
    ("checkout-svc", "High CPU Utilization", "High"),  # risky (scale_asg) -> escalates
    ("image-worker", "Out Of Memory", "Critical"),   # Critical -> human approval
    ("gateway", "5xx Error Spike", "High"),
    ("billing", "Unknown Weird Signal", None),        # unrecognised -> escalates
]


def main() -> None:
    orch = Orchestrator()
    print(f"Running {len(SCENARIOS)} demo incidents in mode={orch.settings.mode}\n")
    for service, alarm, severity in SCENARIOS:
        inc = orch.handle_incident(service, alarm, severity)
        action = inc.remediation.action if inc.remediation else "-"
        outcome = (
            inc.remediation.detail
            if inc.remediation and inc.remediation.executed
            else "awaiting approval / escalated"
        )
        print(f"[{inc.severity.value:8}] {inc.title}")
        print(f"    id         : {inc.id}")
        print(f"    root cause : {inc.root_cause}")
        print(f"    status     : {inc.status.value}")
        print(f"    action     : {action}")
        print(f"    outcome    : {outcome}")
        print(f"    report     : {inc.report_uri}")
        print()


if __name__ == "__main__":
    main()
