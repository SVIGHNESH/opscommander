# OpsCommander - Multi-Agent Response System

An AI-powered, multi-agent system that automatically responds to cloud and DevOps incidents.
Instead of a single model, **seven specialised agents** collaborate to detect, diagnose, recommend,
gate, remediate, and report on incidents - with a human-in-the-loop safety gate before any risky action.

> Built to run **offline out of the box**: every AWS integration (Bedrock, CloudWatch, DynamoDB, S3,
> SNS) has a local mock, so `python scripts/seed_incident.py` works with zero configuration and zero
> cloud credentials. Flip `OPSCOMMANDER_MODE=aws` to talk to real services.

Full documentation is in [`docs/index.html`](docs/index.html) - open it in a browser.

---

## The seven agents

| # | Agent | Responsibility |
|---|-------|----------------|
| 1 | **Detection** | Normalise the CloudWatch alarm/event, score severity, pull the metric snapshot |
| 2 | **Log Analysis** | Read logs, extract exceptions, infer the root cause |
| 3 | **Infrastructure** | Review EC2 / Lambda / API Gateway / ECS health |
| 4 | **Recommendation** | Use **Amazon Bedrock (Claude)** to propose prioritised, machine-actionable fixes |
| 5 | **Approval** | Classify action risk; auto-approve safe actions, **escalate risky/destructive ones** |
| 6 | **Remediation** | Execute the *approved* action (restart Lambda, scale ASG, ...) - never an unapproved one |
| 7 | **Reporting** | Compile the report (JSON / Markdown / PDF), persist it, notify via SNS + Slack |

```
CloudWatch Alarm
      │
      ▼
Detection → Log Analysis → Infrastructure → Recommendation → Approval ──┐
                                                                        │ auto-approved?
                                                       ┌── yes ─────────┤
                                                       ▼                │ no
                                                  Remediation           ▼
                                                       │           (await human)
                                                       ▼           POST /approve
                                                   Reporting ──────────┘
                                                       │
                                                       ▼
                                          Dashboard + Email + SNS + Slack
```

## Quick start

```bash
# 1. Run the seeded demo incidents (no dependencies at all)
python scripts/seed_incident.py

# 2. Optional: create a venv and install the surfaces you want
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"        # api + dashboard + aws + pdf + tests

# 3. Run the pieces
./run.sh demo         # seeded incidents
./run.sh test         # test suite
./run.sh api          # FastAPI on http://localhost:8000  (/docs for Swagger)
./run.sh dashboard    # Streamlit console on http://localhost:8501
```

## API

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/incident` | Create + run an incident |
| `GET`  | `/incident/{id}` | Full incident state |
| `GET`  | `/incidents` | List recent incidents |
| `POST` | `/approve` | Approve a halted incident's remediation |
| `GET`  | `/report/{id}?fmt=markdown\|json` | Download the report |
| `GET`  | `/healthz` | Liveness |

```bash
curl -X POST localhost:8000/incident \
  -H 'content-type: application/json' \
  -d '{"service":"orders-api","alarm":"Database Timeout","severity":"High"}'
```

Sample response:

```json
{
  "id": "inc_ef059c29877b",
  "severity": "High",
  "status": "Resolved",
  "root_cause": "Database connection timeout",
  "recommendation": {"action": "increase_db_connections", "confidence": 0.82},
  "action_taken": {"action": "increase_db_connections", "executed": true, "success": true}
}
```

## Configuration

Everything is environment-driven; see [`.env.example`](.env.example). Key knobs:

| Variable | Default | Meaning |
|----------|---------|---------|
| `OPSCOMMANDER_MODE` | `mock` | `mock` (local fakes) or `aws` (real services) |
| `AWS_REGION` | `us-east-1` | Region for Bedrock/DynamoDB/S3/... |
| `OPSCOMMANDER_BEDROCK_MODEL` | `anthropic.claude-opus-4-8` | Bedrock model id (note the `anthropic.` prefix) |
| `OPSCOMMANDER_AUTO_APPROVE_SEVERITY` | `High` | Safe actions at/below this severity auto-approve; anything riskier escalates |

## Design notes

- **One object, seven agents.** A single `Incident` threads through the pipeline; each agent reads what
  it needs and writes its result back, so the object *is* the audit trail by the time the report is built.
- **Graceful degradation everywhere.** Missing boto3, missing credentials, or a failed Bedrock call all
  fall back to deterministic local behaviour rather than crashing the run.
- **The Approval Agent is the safety boundary.** Destructive actions (`delete_database`, `terminate_ec2`)
  can never be auto-executed; the Remediation Agent refuses to run anything the Approval Agent didn't
  approve.
- **Zero-dependency core.** `src/opscommander/` (minus the API/dashboard/PDF/AWS adapters) runs on the
  standard library alone and is fully unit-tested without any cloud access.

## Layout

```
opscommander/
├── src/opscommander/
│   ├── models.py          # dataclass domain models (Incident, Severity, ...)
│   ├── config.py          # env-driven settings
│   ├── orchestrator.py    # runs the 7 agents; owns the approval gate
│   ├── agents/            # one module per agent
│   ├── aws/               # Bedrock / CloudWatch / infra / notifications (+ mocks)
│   ├── storage/           # DynamoDB + local-file repositories
│   ├── reporting/         # JSON / Markdown / PDF report builder
│   └── api/app.py         # FastAPI
├── dashboard/app.py       # Streamlit operator console
├── scripts/seed_incident.py
├── tests/                 # pytest suite (agents, orchestrator, API)
└── docs/index.html        # full HTML documentation
```
