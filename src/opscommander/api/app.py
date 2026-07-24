"""FastAPI application - the HTTP surface of OpsCommander.

Endpoints (matching the project spec):
    POST /incident          -> create + run an incident
    GET  /incident/{id}      -> incident status
    GET  /incidents          -> list recent incidents
    POST /approve            -> approve a halted incident's remediation
    GET  /report/{id}         -> download the incident report (markdown/json)
    GET  /healthz            -> liveness

Run with:  uvicorn opscommander.api.app:app --reload
"""

from __future__ import annotations

from typing import Any

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import PlainTextResponse
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "FastAPI is required for the API. Install with: pip install 'opscommander[api]'"
    ) from exc

from ..config import get_settings
from ..logging_config import get_logger
from ..models import Incident
from ..orchestrator import Orchestrator
from ..reporting.report_builder import ReportBuilder
from ..storage import get_repository

log = get_logger("api")

app = FastAPI(
    title="OpsCommander",
    description="Multi-agent cloud incident response system.",
    version="0.1.0",
)

_settings = get_settings()
_repo = get_repository(_settings)
_orchestrator = Orchestrator(_settings, _repo)


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class IncidentRequest(BaseModel):
    service: str = Field(..., examples=["orders-api"])
    alarm: str = Field(..., examples=["Timeout"])
    severity: str | None = Field(None, examples=["Critical"])
    source_event: dict[str, Any] = Field(default_factory=dict)


class ApproveRequest(BaseModel):
    incident_id: str
    approved_by: str = "operator"


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "mode": _settings.mode}


@app.post("/incident")
def create_incident(req: IncidentRequest) -> dict[str, Any]:
    incident = _orchestrator.handle_incident(
        service=req.service,
        alarm=req.alarm,
        severity=req.severity,
        source_event=req.source_event,
    )
    return _summary(incident)


@app.get("/incident/{incident_id}")
def get_incident(incident_id: str) -> dict[str, Any]:
    incident = _repo.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident.to_dict()


@app.get("/incidents")
def list_incidents(limit: int = 50) -> dict[str, Any]:
    return {"incidents": [_summary(i) for i in _repo.list(limit=limit)]}


@app.post("/approve")
def approve(req: ApproveRequest) -> dict[str, Any]:
    incident = _orchestrator.resume_after_approval(req.incident_id, req.approved_by)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return _summary(incident)


@app.get("/report/{incident_id}", response_class=PlainTextResponse)
def get_report(incident_id: str, fmt: str = "markdown") -> str:
    incident = _repo.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    builder = ReportBuilder(_settings)
    if fmt == "json":
        import json

        return json.dumps(incident.to_dict(), indent=2, default=str)
    return builder.render_markdown(incident)


# --------------------------------------------------------------------------- #
def _summary(incident: Incident) -> dict[str, Any]:
    return {
        "id": incident.id,
        "service": incident.service,
        "alarm": incident.alarm,
        "title": incident.title,
        "severity": incident.severity.value,
        "status": incident.status.value,
        "root_cause": incident.root_cause,
        "recommendation": (
            incident.recommendations[0].to_dict()
            if incident.recommendations
            else None
        ),
        "approval": incident.approval.to_dict() if incident.approval else None,
        "action_taken": incident.remediation.to_dict() if incident.remediation else None,
        "report_uri": incident.report_uri,
        "updated_at": incident.updated_at,
    }
