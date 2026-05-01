from __future__ import annotations

from fastapi.testclient import TestClient

from app.agent_framework.server.app import app


def test_health_reports_runtime_storage_and_checkpointing():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["config"]["storage_backend"] == "postgres"
    assert data["storage"]["backend"] == "postgres"
    assert data["checkpointing"]["backend"] == "postgres"
    assert "root" in data["app"]
    assert "data_root" in data["paths"]
