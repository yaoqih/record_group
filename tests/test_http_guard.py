import json
import logging
import os

import pytest
from fastapi.testclient import TestClient

os.environ["RECORDFLOW_SKIP_DEFAULT_APP"] = "1"

from recordflow_agent import api as api_module
from recordflow_agent.api import create_app
from recordflow_agent.http_guard import RateLimitRule, SlidingWindowRateLimiter, sensitive_rate_limit_scope
from recordflow_agent.sqlite_repository import SQLiteRepository


HTTP_GUARD_LOGGER = "uvicorn.error.recordflow.http_guard"


def test_request_id_is_forwarded_and_access_log_omits_query_and_credentials(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setenv("RECORDFLOW_ENV", "development")
    monkeypatch.setenv("RECORDFLOW_RATE_LIMIT_ENABLED", "false")
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    client = TestClient(create_app(repo))

    with caplog.at_level(logging.INFO, logger=HTTP_GUARD_LOGGER):
        response = client.get(
            "/health?site_token=query-secret",
            headers={"X-Request-ID": "client-request-123", "Authorization": "Bearer header-secret"},
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "client-request-123"
    records = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == HTTP_GUARD_LOGGER and '"event":"http_request"' in record.getMessage()
    ]
    assert records[-1]["method"] == "GET"
    assert records[-1]["path"] == "/health"
    assert records[-1]["status"] == 200
    assert records[-1]["request_id"] == "client-request-123"
    assert "duration_ms" in records[-1]
    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert "query-secret" not in combined
    assert "header-secret" not in combined
    repo.close()


def test_invalid_request_id_is_replaced(tmp_path, monkeypatch):
    monkeypatch.setenv("RECORDFLOW_ENV", "development")
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    client = TestClient(create_app(repo))

    response = client.get("/health", headers={"X-Request-ID": "invalid request id"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "invalid request id"
    assert len(response.headers["X-Request-ID"]) == 32
    repo.close()


def test_sensitive_endpoint_rate_limit_returns_retry_after(tmp_path, monkeypatch):
    monkeypatch.setenv("RECORDFLOW_ENV", "development")
    monkeypatch.setenv("RECORDFLOW_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RECORDFLOW_RATE_LIMIT_AUTH_REQUESTS", "1")
    monkeypatch.setenv("RECORDFLOW_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("RECORDFLOW_ENABLE_DEV_LOGIN", "1")
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    client = TestClient(create_app(repo))

    login_body = {
        "nickname": "Local",
        "agreement_version": "v2",
        "agreement_accepted": True,
    }
    first = client.post("/site/auth/dev/login", json=login_body)
    limited = client.post("/site/auth/dev/login", json=login_body)

    assert first.status_code == 200
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1
    assert limited.headers["X-Request-ID"]
    repo.close()


def test_rate_limiter_evicts_oldest_key_when_capacity_is_reached():
    limiter = SlidingWindowRateLimiter(
        enabled=True,
        window_seconds=60,
        rules={"auth": RateLimitRule("auth", 2)},
        max_keys=2,
    )

    assert limiter.retry_after("auth", "client-1", now=1) is None
    assert limiter.retry_after("auth", "client-2", now=1) is None
    assert limiter.retry_after("auth", "client-3", now=1) is None

    assert len(limiter._buckets) == 2
    assert ("auth", "client-1") not in limiter._buckets


def test_task_upload_rate_limit_only_applies_to_post_requests():
    assert sensitive_rate_limit_scope("/site/me/tasks", "POST") == "task_upload"
    assert sensitive_rate_limit_scope("/site/me/tasks", "GET") is None


def test_production_requires_explicit_recordflow_session_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "load_dotenv", lambda: None)
    monkeypatch.setenv("RECORDFLOW_ENV", "production")
    monkeypatch.delenv("RECORDFLOW_SESSION_SECRET", raising=False)
    monkeypatch.setenv("SESSION_SECRET", "legacy-secret-must-not-be-used")
    monkeypatch.setenv("RECORDFLOW_APP_API_KEY", "api-key-must-not-be-used")
    repo = SQLiteRepository(tmp_path / "recordflow.db")

    with pytest.raises(RuntimeError, match="RECORDFLOW_SESSION_SECRET is required"):
        create_app(repo)

    repo.close()


def test_production_requires_admin_api_key(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "load_dotenv", lambda: None)
    monkeypatch.setenv("RECORDFLOW_ENV", "production")
    monkeypatch.setenv("RECORDFLOW_SESSION_SECRET", "session-secret")
    monkeypatch.delenv("RECORDFLOW_APP_API_KEY", raising=False)
    repo = SQLiteRepository(tmp_path / "recordflow.db")

    with pytest.raises(RuntimeError, match="RECORDFLOW_APP_API_KEY is required"):
        create_app(repo)

    repo.close()


def test_production_requires_virtual_payment_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "load_dotenv", lambda: None)
    monkeypatch.setenv("RECORDFLOW_ENV", "production")
    monkeypatch.setenv("RECORDFLOW_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("RECORDFLOW_APP_API_KEY", "admin-secret")
    for name in (
        "WECHAT_MINIAPP_APPID",
        "WECHAT_VIRTUAL_OFFER_ID",
        "WECHAT_VIRTUAL_PRODUCTION_APPKEY",
        "WECHAT_VIRTUAL_NOTIFY_TOKEN",
        "WECHAT_VIRTUAL_NOTIFY_AES_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    repo = SQLiteRepository(tmp_path / "recordflow.db")

    with pytest.raises(RuntimeError, match="virtual-payment configuration"):
        create_app(repo)

    repo.close()


def test_query_session_token_remains_compatible_but_logs_deprecation(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setenv("RECORDFLOW_ENV", "development")
    monkeypatch.setenv("RECORDFLOW_SESSION_SECRET", "test-session-secret")
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    client = TestClient(create_app(repo))
    user = client.post("/site/users", json={"name": "Alice"}).json()["user"]
    token = api_module.create_site_session_token(user["id"])

    with caplog.at_level(logging.WARNING, logger=HTTP_GUARD_LOGGER):
        response = client.get(f"/site/me?site_token={token}")

    assert response.status_code == 200
    warnings = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == HTTP_GUARD_LOGGER
        and '"event":"deprecated_site_token_query"' in record.getMessage()
    ]
    assert warnings[-1]["path"] == "/site/me"
    assert warnings[-1]["request_id"] == response.headers["X-Request-ID"]
    assert token not in "\n".join(record.getMessage() for record in caplog.records)
    repo.close()
