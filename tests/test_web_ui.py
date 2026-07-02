from fastapi.testclient import TestClient

from recordflow_agent.api import create_app
from recordflow_agent.sqlite_repository import SQLiteRepository


def test_user_admin_and_agreement_pages_are_exposed(tmp_path):
    app = create_app(SQLiteRepository(tmp_path / "recordflow.db"))
    client = TestClient(app)

    user_response = client.get("/")
    admin_response = client.get("/admin")
    agreement_response = client.get("/agreement")

    assert user_response.status_code == 200
    assert "<div id=\"root\"></div>" in user_response.text or "上传到服务器并创建任务" in user_response.text
    assert admin_response.status_code == 200
    assert "ASR 管理端" in admin_response.text
    assert "用户与点数" in admin_response.text
    assert agreement_response.status_code == 200
    assert "用户协议" in agreement_response.text


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
