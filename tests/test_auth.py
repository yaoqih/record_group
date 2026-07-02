from fastapi.testclient import TestClient

from recordflow_agent.api import create_app
from recordflow_agent.sqlite_repository import SQLiteRepository


def test_api_allows_requests_when_app_api_key_is_not_configured(tmp_path, monkeypatch):
    monkeypatch.delenv("RECORDFLOW_APP_API_KEY", raising=False)
    app = create_app(SQLiteRepository(tmp_path / "recordflow.db"))
    client = TestClient(app)

    response = client.post(
        "/workspaces",
        json={"name": "RecordFlow product", "profile": "project_meeting"},
    )

    assert response.status_code == 200


def test_api_requires_x_api_key_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("RECORDFLOW_APP_API_KEY", "secret")
    app = create_app(SQLiteRepository(tmp_path / "recordflow.db"))
    client = TestClient(app)

    missing = client.post(
        "/workspaces",
        json={"name": "RecordFlow product", "profile": "project_meeting"},
    )
    wrong = client.post(
        "/workspaces",
        json={"name": "RecordFlow product", "profile": "project_meeting"},
        headers={"X-API-Key": "wrong"},
    )
    ok = client.post(
        "/workspaces",
        json={"name": "RecordFlow product", "profile": "project_meeting"},
        headers={"X-API-Key": "secret"},
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert ok.status_code == 200


def test_health_does_not_require_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("RECORDFLOW_APP_API_KEY", "secret")
    app = create_app(SQLiteRepository(tmp_path / "recordflow.db"))
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
