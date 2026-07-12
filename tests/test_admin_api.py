from datetime import datetime

from fastapi.testclient import TestClient

from recordflow_agent.api import create_app, recordflow_environment
from recordflow_agent.sqlite_repository import SQLiteRepository


ADMIN_HEADERS = {"X-API-Key": "admin-secret"}


def test_admin_environment_defaults_to_development(monkeypatch):
    monkeypatch.delenv("RECORDFLOW_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    assert recordflow_environment() == "development"


def test_admin_meta_reports_current_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("RECORDFLOW_APP_API_KEY", "admin-secret")
    monkeypatch.setenv("RECORDFLOW_ENV", "staging")
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    client = TestClient(create_app(repo))

    missing = client.get("/site/admin/meta")
    response = client.get("/site/admin/meta", headers=ADMIN_HEADERS)

    assert missing.status_code == 401
    assert response.status_code == 200
    assert response.json()["environment"] == "staging"
    assert response.json()["service_name"] == "RecordFlow"
    assert datetime.fromisoformat(response.json()["server_time"].replace("Z", "+00:00")).tzinfo
    repo.close()


def test_admin_can_create_and_update_user(tmp_path, monkeypatch):
    monkeypatch.setenv("RECORDFLOW_APP_API_KEY", "admin-secret")
    monkeypatch.setenv("RECORDFLOW_ENV", "testing")
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    client = TestClient(create_app(repo))

    created = client.post(
        "/site/admin/users",
        headers=ADMIN_HEADERS,
        json={"name": "  Alice  ", "role": "admin", "initial_points": 30},
    )

    assert created.status_code == 200
    user = created.json()["user"]
    assert user["name"] == "Alice"
    assert user["role"] == "admin"
    assert user["points_balance"] == 30

    renamed = client.patch(
        f"/site/admin/users/{user['id']}",
        headers=ADMIN_HEADERS,
        json={"name": "Alice Zhang"},
    )
    changed_role = client.patch(
        f"/site/admin/users/{user['id']}",
        headers=ADMIN_HEADERS,
        json={"role": "user"},
    )

    assert renamed.status_code == 200
    assert renamed.json()["user"]["name"] == "Alice Zhang"
    assert renamed.json()["user"]["role"] == "admin"
    assert changed_role.status_code == 200
    assert changed_role.json()["user"]["name"] == "Alice Zhang"
    assert changed_role.json()["user"]["role"] == "user"

    dashboard = client.get("/site/admin/dashboard", headers=ADMIN_HEADERS).json()
    initial_entry = next(item for item in dashboard["point_ledger"] if item["user_id"] == user["id"])
    assert initial_entry["delta"] == 30
    assert initial_entry["kind"] == "admin_adjustment_credit"
    repo.close()


def test_admin_point_adjustments_are_atomic_and_cannot_overdraw(tmp_path, monkeypatch):
    monkeypatch.setenv("RECORDFLOW_APP_API_KEY", "admin-secret")
    monkeypatch.setenv("RECORDFLOW_ENV", "testing")
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    client = TestClient(create_app(repo))
    user = client.post(
        "/site/admin/users",
        headers=ADMIN_HEADERS,
        json={"name": "Bob", "initial_points": 20},
    ).json()["user"]

    debit = client.post(
        f"/site/admin/users/{user['id']}/points",
        headers=ADMIN_HEADERS,
        json={"delta": -7, "note": "support correction"},
    )
    overdraw = client.post(
        f"/site/admin/users/{user['id']}/points",
        headers=ADMIN_HEADERS,
        json={"delta": -14},
    )
    zero = client.post(
        f"/site/admin/users/{user['id']}/points",
        headers=ADMIN_HEADERS,
        json={"delta": 0},
    )

    assert debit.status_code == 200
    assert debit.json()["user"]["points_balance"] == 13
    assert overdraw.status_code == 400
    assert overdraw.json()["detail"] == "Insufficient points."
    assert zero.status_code == 400

    dashboard = client.get("/site/admin/dashboard", headers=ADMIN_HEADERS).json()
    saved_user = next(item for item in dashboard["users"] if item["id"] == user["id"])
    entries = [item for item in dashboard["point_ledger"] if item["user_id"] == user["id"]]
    assert saved_user["points_balance"] == 13
    assert [(item["delta"], item["kind"]) for item in entries] == [
        (-7, "admin_adjustment_debit"),
        (20, "admin_adjustment_credit"),
    ]
    repo.close()


def test_admin_user_validation_and_missing_user_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("RECORDFLOW_APP_API_KEY", "admin-secret")
    monkeypatch.setenv("RECORDFLOW_ENV", "testing")
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    client = TestClient(create_app(repo))

    invalid_role = client.post(
        "/site/admin/users",
        headers=ADMIN_HEADERS,
        json={"name": "Operator", "role": "owner"},
    )
    negative_initial = client.post(
        "/site/admin/users",
        headers=ADMIN_HEADERS,
        json={"name": "Operator", "initial_points": -1},
    )
    empty_patch = client.patch(
        "/site/admin/users/missing",
        headers=ADMIN_HEADERS,
        json={},
    )
    missing_adjustment = client.post(
        "/site/admin/users/missing/points",
        headers=ADMIN_HEADERS,
        json={"delta": 1},
    )

    assert invalid_role.status_code == 400
    assert negative_initial.status_code == 400
    assert empty_patch.status_code == 400
    assert missing_adjustment.status_code == 404
    repo.close()
