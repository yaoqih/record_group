from fastapi.testclient import TestClient

from recordflow_agent.api import create_app
from recordflow_agent.sqlite_repository import SQLiteRepository


def test_public_user_page_is_disabled_but_admin_and_agreement_are_exposed(tmp_path):
    app = create_app(SQLiteRepository(tmp_path / "recordflow.db"))
    client = TestClient(app)

    user_response = client.get("/")
    admin_response = client.get("/admin")
    agreement_response = client.get("/agreement")

    assert user_response.status_code == 404
    assert admin_response.status_code == 200
    assert "<div id=\"root\"></div>" in admin_response.text or "ASR 管理端" in admin_response.text
    assert agreement_response.status_code == 200
    assert "用户协议" in agreement_response.text
    assert "服务提供方" in agreement_response.text
    assert "1375626371@qq.com" in agreement_response.text


def test_mobile_upload_page_uses_direct_storage_upload(tmp_path):
    app = create_app(SQLiteRepository(tmp_path / "recordflow.db"))
    response = TestClient(app).get("/mobile-upload")

    assert response.status_code == 200
    assert "/site/me/tasks/direct-upload/init" in response.text
    assert "/site/me/tasks/direct-upload/complete" in response.text
    assert "xhr.open(target.method || 'POST', target.url)" in response.text


def test_dashboard_endpoint_still_returns_workspace_results(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)
    workspace_id = client.post(
        "/workspaces",
        json={"name": "RecordFlow product", "profile": "detailed_summary"},
    ).json()["id"]
    client.post(
        f"/workspaces/{workspace_id}/records",
        json={
            "title": "meeting 1",
            "text": "决定先做文本导入 MVP。张三负责后端，周五前完成。",
            "use_llm": False,
        },
    )

    response = client.get("/dashboard")

    assert response.status_code == 200
    data = response.json()
    assert data["record_count"] >= 1
    assert data["workspaces"][0]["records"]
