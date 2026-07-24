import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_settings, monkeypatch):
    # Import inside the fixture so the app picks up the isolated data dir.
    import importlib

    import opscommander.api.app as app_module

    importlib.reload(app_module)
    return TestClient(app_module.app)


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_create_and_get_incident(client):
    resp = client.post(
        "/incident", json={"service": "orders-api", "alarm": "Database Timeout", "severity": "High"}
    )
    assert resp.status_code == 200
    body = resp.json()
    inc_id = body["id"]
    assert body["status"] == "Resolved"

    got = client.get(f"/incident/{inc_id}")
    assert got.status_code == 200
    assert got.json()["id"] == inc_id


def test_report_endpoint(client):
    inc_id = client.post(
        "/incident", json={"service": "orders-api", "alarm": "Database Timeout"}
    ).json()["id"]
    md = client.get(f"/report/{inc_id}")
    assert md.status_code == 200
    assert "Incident Report" in md.text


def test_approve_flow(client):
    inc_id = client.post(
        "/incident", json={"service": "checkout-svc", "alarm": "High CPU Utilization", "severity": "High"}
    ).json()["id"]
    resp = client.post("/approve", json={"incident_id": inc_id, "approved_by": "tester"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "Resolved"
