from fastapi.testclient import TestClient

from recordflow_agent.api import create_app
from recordflow_agent.sqlite_repository import SQLiteRepository
from recordflow_agent.worker import process_next_job


def test_api_processes_record_and_exposes_state_and_review_queue(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)

    workspace_response = client.post(
        "/workspaces",
        json={"name": "RecordFlow product", "profile": "project_meeting"},
    )
    assert workspace_response.status_code == 200
    workspace_id = workspace_response.json()["id"]

    record_response = client.post(
        f"/workspaces/{workspace_id}/records",
        json={
            "title": "meeting 1",
            "text": "决定先做文本导入 MVP。张三负责后端，周五前完成。",
            "use_llm": False,
        },
    )
    assert record_response.status_code == 200
    assert record_response.json()["digest"]["one_line_summary"]

    state_response = client.get(f"/workspaces/{workspace_id}/state")
    assert state_response.status_code == 200
    assert len(state_response.json()["state_objects"]) >= 2

    review_response = client.get(f"/workspaces/{workspace_id}/review")
    assert review_response.status_code == 200
    pending = review_response.json()["review_items"]
    assert len(pending) >= 1

    accept_response = client.post(
        f"/review/{pending[0]['id']}",
        json={"status": "accepted"},
    )
    assert accept_response.status_code == 200
    assert accept_response.json()["status"] == "accepted"
    repo.close()


def test_health_endpoint(tmp_path):
    app = create_app(SQLiteRepository(tmp_path / "recordflow.db"))
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_serves_admin_frontend_when_directory_exists(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    frontend_dir = tmp_path / "frontend_dist"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text("<!doctype html><html><body>frontend ok</body></html>", encoding="utf-8")
    app = create_app(repo)
    app.state.frontend_dist = frontend_dir
    client = TestClient(app)

    response = client.get("/admin")

    assert response.status_code == 200
    assert "frontend ok" in response.text
    repo.close()


def test_api_does_not_serve_public_user_frontend(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    frontend_dir = tmp_path / "frontend_dist"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text("<!doctype html><html><body>frontend ok</body></html>", encoding="utf-8")
    monkeypatch.setenv("RECORDFLOW_APP_API_KEY", "secret-key")
    app = create_app(repo)
    app.state.frontend_dist = frontend_dir
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 404
    assert "frontend ok" not in response.text
    repo.close()


def test_api_allows_frontend_assets_without_api_key(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    frontend_dir = tmp_path / "frontend_dist"
    assets_dir = frontend_dir / "assets"
    assets_dir.mkdir(parents=True)
    (frontend_dir / "index.html").write_text("<!doctype html><html><body>frontend ok</body></html>", encoding="utf-8")
    (assets_dir / "app.js").write_text("console.log('ok')", encoding="utf-8")
    monkeypatch.setenv("RECORDFLOW_APP_API_KEY", "secret-key")
    app = create_app(repo)
    app.state.frontend_dist = frontend_dir
    client = TestClient(app)

    response = client.get("/assets/app.js")

    assert response.status_code == 200
    assert "console.log('ok')" in response.text
    repo.close()


def test_api_can_enqueue_record_job_and_return_job_status(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)
    workspace_id = client.post(
        "/workspaces",
        json={"name": "RecordFlow product", "profile": "project_meeting"},
    ).json()["id"]

    response = client.post(
        f"/workspaces/{workspace_id}/records",
        json={
            "title": "meeting 1",
            "text": "张三负责后端，周五前完成。",
            "use_llm": False,
            "async_mode": True,
        },
    )
    job_id = response.json()["job"]["id"]
    job_response = client.get(f"/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["job"]["status"] == "pending"
    assert job_response.status_code == 200
    assert job_response.json()["job"]["id"] == job_id
    repo.close()


def test_api_exposes_digest_for_completed_async_record_job(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)
    workspace_id = client.post(
        "/workspaces",
        json={"name": "RecordFlow product", "profile": "project_meeting"},
    ).json()["id"]
    enqueue_response = client.post(
        f"/workspaces/{workspace_id}/records",
        json={
            "title": "meeting 1",
            "text": "决定先做文本导入 MVP。张三负责后端，周五前完成。",
            "use_llm": False,
            "async_mode": True,
        },
    )
    job_id = enqueue_response.json()["job"]["id"]

    assert process_next_job(repo) is True
    job_response = client.get(f"/jobs/{job_id}")
    record_id = job_response.json()["job"]["record_id"]
    digest_response = client.get(f"/records/{record_id}/digest")

    assert job_response.status_code == 200
    assert job_response.json()["digest"]["record_id"] == record_id
    assert digest_response.status_code == 200
    assert digest_response.json()["digest"]["record_id"] == record_id
    assert digest_response.json()["digest"]["sections"]
    repo.close()


def test_api_can_query_and_patch_state_objects(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)
    workspace_id = client.post(
        "/workspaces",
        json={"name": "RecordFlow product", "profile": "project_meeting"},
    ).json()["id"]

    client.post(
        f"/workspaces/{workspace_id}/records",
        json={
            "title": "meeting 1",
            "text": "决定先做文本导入 MVP。张三负责后端，周五前完成。",
            "use_llm": False,
        },
    )

    state_response = client.get(f"/workspaces/{workspace_id}/state?type=Task")
    assert state_response.status_code == 200
    tasks = [item for item in state_response.json()["state_objects"] if item["type"] == "Task"]
    assert len(tasks) == 1

    patch_response = client.patch(
        f"/state/objects/{tasks[0]['id']}",
        json={"summary": "更新后的任务摘要", "status": "closed"},
    )
    assert patch_response.status_code == 200
    patched = patch_response.json()["state_object"]
    assert patched["summary"] == "更新后的任务摘要"
    assert patched["status"] == "closed"

    archive_response = client.post(f"/state/objects/{tasks[0]['id']}/archive")
    assert archive_response.status_code == 200
    archived = archive_response.json()["state_object"]
    assert archived["status"] == "archived"
    repo.close()


def test_api_can_close_reopen_and_clarify_state_object(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)
    workspace_id = client.post(
        "/workspaces",
        json={"name": "RecordFlow product", "profile": "project_meeting"},
    ).json()["id"]

    client.post(
        f"/workspaces/{workspace_id}/records",
        json={
            "title": "meeting 1",
            "text": "张三负责后端，周五前完成。",
            "use_llm": False,
        },
    )
    task = client.get(f"/workspaces/{workspace_id}/state?type=Task").json()["state_objects"][0]

    close_response = client.post(f"/state/objects/{task['id']}/close")
    reopen_response = client.post(f"/state/objects/{task['id']}/reopen")
    clarify_response = client.post(
        f"/state/objects/{task['id']}/clarify",
        json={"note": "用户确认后端范围只包含 API。"},
    )

    assert close_response.status_code == 200
    assert close_response.json()["state_object"]["status"] == "closed"
    assert reopen_response.status_code == 200
    assert reopen_response.json()["state_object"]["status"] == "open"
    assert clarify_response.status_code == 200
    clarified = clarify_response.json()["state_object"]
    assert clarified["payload"]["clarifications"] == ["用户确认后端范围只包含 API。"]
    repo.close()


def test_api_can_apply_digest_patch_without_reprocessing_record(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)
    workspace_id = client.post(
        "/workspaces",
        json={"name": "RecordFlow product", "profile": "project_meeting"},
    ).json()["id"]
    record_response = client.post(
        f"/workspaces/{workspace_id}/records",
        json={
            "title": "meeting 1",
            "text": "We decided to keep the target group simple. Sarah is responsible for sending interface notes by Friday.",
            "use_llm": False,
        },
    )
    digest = record_response.json()["digest"]
    section_id = digest["sections"][0]["id"]

    patch_response = client.post(
        "/digest/patch",
        json={
            "digest": digest,
            "patch": {
                "op": "replace_section",
                "section_id": section_id,
                "summary": "用户确认后的章节摘要。",
                "key_points": ["只更新这一节，不重新处理原始 Record。"],
            },
        },
    )

    assert patch_response.status_code == 200
    patched = patch_response.json()["digest"]
    patched_section = next(section for section in patched["sections"] if section["id"] == section_id)
    assert patched_section["summary"] == "用户确认后的章节摘要。"
    assert patched_section["evidence_segment_ids"] == digest["sections"][0]["evidence_segment_ids"]
    assert patched_section["patch_history"][-1]["op"] == "replace_section"
    assert any(item.get("kind") == "digest_patch" for item in patched["processing_trace"])
    repo.close()


def test_api_can_patch_persisted_digest_without_client_resending_full_digest(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)
    workspace_id = client.post(
        "/workspaces",
        json={"name": "RecordFlow product", "profile": "project_meeting"},
    ).json()["id"]
    record_response = client.post(
        f"/workspaces/{workspace_id}/records",
        json={
            "title": "meeting 1",
            "text": "We decided to keep the target group simple. Sarah is responsible for sending interface notes by Friday.",
            "use_llm": False,
        },
    )
    digest = record_response.json()["digest"]
    record_id = digest["record_id"]
    section_id = digest["sections"][0]["id"]

    patch_response = client.post(
        f"/records/{record_id}/digest/patch",
        json={
            "patch": {
                "op": "insert_key_point",
                "section_id": section_id,
                "text": "用户补充确认：这一点需要在后续回放中突出显示。",
            },
        },
    )
    digest_response = client.get(f"/records/{record_id}/digest")

    assert patch_response.status_code == 200
    patched_section = next(
        section for section in digest_response.json()["digest"]["sections"] if section["id"] == section_id
    )
    assert "用户补充确认：这一点需要在后续回放中突出显示。" in patched_section["key_points"]
    assert patched_section["evidence_segment_ids"] == digest["sections"][0]["evidence_segment_ids"]
    repo.close()
