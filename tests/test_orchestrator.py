from opscommander.models import IncidentStatus
from opscommander.orchestrator import Orchestrator


def test_full_pipeline_safe_action_resolves(tmp_settings):
    orch = Orchestrator(tmp_settings)
    inc = orch.handle_incident("orders-api", "Database Timeout", "High")

    # DB-timeout -> increase_db_connections (safe) -> auto-approved -> remediated.
    assert inc.status == IncidentStatus.RESOLVED
    assert inc.remediation is not None
    assert inc.remediation.executed is True
    assert inc.report_uri
    # Every agent ran and recorded a result.
    for stage in (
        "detection",
        "log_analysis",
        "infrastructure",
        "recommendation",
        "approval",
        "remediation",
        "reporting",
    ):
        assert stage in inc.agent_results


def test_unrecognised_signal_escalates(tmp_settings):
    orch = Orchestrator(tmp_settings)
    # An unrecognised signal yields a `manual_investigation` recommendation,
    # which the approval gate treats as risky -> never auto-remediated.
    inc = orch.handle_incident("billing", "Unknown Weird Signal")
    assert inc.status in (
        IncidentStatus.AWAITING_APPROVAL,
        IncidentStatus.ESCALATED,
    )
    assert inc.remediation is None or inc.remediation.executed is False


def test_resume_after_approval_remediates(tmp_settings):
    orch = Orchestrator(tmp_settings)
    # High-CPU -> scale_asg is "risky" -> awaits approval.
    inc = orch.handle_incident("checkout-svc", "High CPU Utilization", "High")
    assert inc.status == IncidentStatus.AWAITING_APPROVAL

    resumed = orch.resume_after_approval(inc.id, "sre-oncall")
    assert resumed is not None
    assert resumed.status == IncidentStatus.RESOLVED
    assert resumed.remediation.executed is True
    assert "sre-oncall" in resumed.approval.reason


def test_persistence_roundtrip(tmp_settings):
    orch = Orchestrator(tmp_settings)
    inc = orch.handle_incident("orders-api", "Database Timeout", "High")
    loaded = orch.repo.get(inc.id)
    assert loaded is not None
    assert loaded.id == inc.id
    assert loaded.root_cause == inc.root_cause
    assert len(loaded.timeline) == len(inc.timeline)
