"""Recommendation Agent.

Uses Amazon Bedrock (Anthropic Claude) to turn the incident context - root
cause, infrastructure health, metrics - into prioritised, machine-actionable
fix recommendations. Falls back to a deterministic rule engine when Bedrock is
not configured.
"""

from __future__ import annotations

from ..aws.bedrock import BedrockLLM
from ..models import AgentResult, Incident, Recommendation, _now
from .base import Agent


class RecommendationAgent(Agent):
    name = "recommendation"

    def __init__(self, settings=None, llm: BedrockLLM | None = None):
        super().__init__(settings)
        self.llm = llm or BedrockLLM(self.settings)

    def run(self, incident: Incident) -> AgentResult:
        started = _now()
        context = self._build_context(incident)
        raw = self.llm.recommend(context)

        recs = [self._to_recommendation(r) for r in raw if r.get("action")]
        recs.sort(key=lambda r: r.confidence, reverse=True)
        incident.recommendations = recs

        top = recs[0].title if recs else "none"
        incident.log(
            self.name,
            f"Generated {len(recs)} recommendation(s); top: {top}",
            actions=[r.action for r in recs],
        )
        return self._result(
            ok=bool(recs),
            summary=f"{len(recs)} recommendation(s); top action="
            f"{recs[0].action if recs else 'none'}",
            started_at=started,
            recommendations=[r.to_dict() for r in recs],
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_context(incident: Incident) -> dict:
        infra = incident.agent_results.get("infrastructure")
        detection = incident.agent_results.get("detection")
        return {
            "service": incident.service,
            "alarm": incident.alarm,
            "severity": incident.severity.value,
            "root_cause": incident.root_cause,
            "metrics": detection.data.get("metrics") if detection else {},
            "health": infra.data.get("health") if infra else {},
        }

    @staticmethod
    def _to_recommendation(r: dict) -> Recommendation:
        return Recommendation(
            title=str(r.get("title", "Recommendation")),
            rationale=str(r.get("rationale", "")),
            action=str(r.get("action", "manual_investigation")),
            confidence=float(r.get("confidence", 0.5)),
            references=list(r.get("references", []) or []),
        )
