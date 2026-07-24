from opscommander.agents import (
    ApprovalAgent,
    IncidentDetectionAgent,
    InfrastructureAgent,
    LogAnalysisAgent,
    RecommendationAgent,
)
from opscommander.models import Incident, Severity


def _run_upto_recommendation(incident, settings):
    IncidentDetectionAgent(settings).run(incident) and None
    incident.record(IncidentDetectionAgent(settings).run(incident))
    incident.record(LogAnalysisAgent(settings).run(incident))
    incident.record(InfrastructureAgent(settings).run(incident))
    incident.record(RecommendationAgent(settings).run(incident))
    return incident


def test_detection_scores_severity(tmp_settings):
    inc = Incident(service="orders-api", alarm="Database Timeout")
    res = IncidentDetectionAgent(tmp_settings).run(inc)
    assert res.ok
    assert inc.severity in (Severity.HIGH, Severity.CRITICAL)
    assert inc.title


def test_log_analysis_infers_db_timeout(tmp_settings):
    inc = Incident(service="orders-api", alarm="Database Timeout")
    LogAnalysisAgent(tmp_settings).run(inc)
    assert "timeout" in (inc.root_cause or "").lower()


def test_recommendation_produces_actions(tmp_settings):
    inc = Incident(service="orders-api", alarm="Database Timeout")
    _run_upto_recommendation(inc, tmp_settings)
    assert inc.recommendations
    assert all(r.action for r in inc.recommendations)


def test_approval_escalates_destructive(tmp_settings):
    inc = Incident(service="billing", alarm="issue")
    from opscommander.models import Recommendation

    inc.recommendations = [
        Recommendation(title="Delete DB", rationale="", action="delete_database")
    ]
    res = ApprovalAgent(tmp_settings).run(inc)
    assert not res.ok
    assert inc.approval is not None
    assert inc.approval.risk == "destructive"
    assert inc.approval.approved is False


def test_approval_auto_approves_safe_action(tmp_settings):
    inc = Incident(service="orders-api", alarm="timeout", severity=Severity.HIGH)
    from opscommander.models import Recommendation

    inc.recommendations = [
        Recommendation(title="Restart", rationale="", action="restart_lambda")
    ]
    res = ApprovalAgent(tmp_settings).run(inc)
    assert res.ok
    assert inc.approval.approved is True
    assert inc.approval.auto is True
