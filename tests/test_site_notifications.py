import json
import os
from pathlib import Path

os.environ["RECORDFLOW_SKIP_DEFAULT_APP"] = "1"

import pytest
from fastapi.testclient import TestClient

from recordflow_agent import worker as worker_module
from recordflow_agent.api import create_app, create_site_session_token
from recordflow_agent.asr_site import AGREEMENT_VERSION, ASRSiteStore
from recordflow_agent.profiles import load_profile
from recordflow_agent.sqlite_repository import SQLiteRepository
from recordflow_agent.worker import (
    process_next_job,
    recover_pending_site_notifications,
    run_worker,
)


def create_pending_task(store, workspace_id, user_id, local_path, task_id="task-notify"):
    return store.create_pending_task(
        task_id=task_id,
        user_id=user_id,
        workspace_id=workspace_id,
        title="meeting.mp3",
        source_name="meeting.mp3",
        content_type="audio/mpeg",
        original_size_bytes=1024,
        duration_seconds=30,
        points_cost=1,
        charge_basis="30.0s -> 1 points",
        agreement_version=AGREEMENT_VERSION,
        local_file_path=str(local_path),
    )


def test_start_endpoint_persists_notification_preference(tmp_path, monkeypatch):
    monkeypatch.setenv("RECORDFLOW_ENV", "testing")
    monkeypatch.setenv("RECORDFLOW_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("WECHAT_MINIAPP_APPID", "wx-test")
    monkeypatch.setenv("WECHAT_MINIAPP_SECRET", "secret")
    monkeypatch.setenv("WECHAT_SUBSCRIBE_TASK_COMPLETE_TEMPLATE_ID", "template-1")
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    workspace_id = repo.create_workspace("ASR", "detailed_summary")
    local_path = tmp_path / "meeting.mp3"
    local_path.write_bytes(b"audio")
    store = ASRSiteStore(repo)
    try:
        user = store.create_user("Alice")
        store.add_points(user["id"], delta=5, kind="test")
        task = create_pending_task(store, workspace_id, user["id"], local_path)
        assert task["notify_on_complete"] is False
    finally:
        store.close()

    app = create_app(repo)
    client = TestClient(app)
    token = create_site_session_token(user["id"])
    headers = {"Authorization": f"Bearer {token}"}
    detail = client.get(f"/site/me/tasks/{task['id']}", headers=headers)
    started = client.post(
        f"/site/me/tasks/{task['id']}/start",
        json={
            "confirm_points": True,
            "notify_on_complete": True,
            "notification_template_id": "template-1",
        },
        headers=headers,
    )
    store = ASRSiteStore(repo)
    try:
        persisted = store.get_task(task["id"])
        assert detail.status_code == 200
        assert detail.json()["notification_config"] == {
            "enabled": True,
            "template_id": "template-1",
        }
        assert started.status_code == 200
        assert started.json()["task"]["notify_on_complete"] is True
        assert persisted["notify_on_complete"] is True
        assert store.get_user(user["id"])["points_balance"] == 4
    finally:
        store.close()
        repo.close()


def test_worker_notification_failure_does_not_fail_completed_task(tmp_path, monkeypatch):
    monkeypatch.setenv("WECHAT_MINIAPP_APPID", "wx-test")
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    local_path = tmp_path / "meeting.mp3"
    local_path.write_bytes(b"audio")
    store = ASRSiteStore(repo)
    try:
        user = store.get_or_create_wechat_user(
            appid="wx-test",
            openid="openid-1",
            unionid=None,
            session_key="session-key",
            signup_points=5,
        )
        task = create_pending_task(store, workspace_id, user["id"], local_path)
        store.mark_task_starting_with_points(
            task["id"],
            user["id"],
            notify_on_complete=True,
            notification_template_id="template-1",
        )
        media_id = repo.add_media_record(
            workspace_id=workspace_id,
            source_name="meeting.mp3",
            stored_name="meeting.ogg",
            url="https://cdn.example.com/meeting.ogg",
            public_url="https://public.example.com/meeting.ogg",
            object_name="uploads/meeting.ogg",
            content_type="audio/ogg",
            original_size_bytes=1024,
            compressed_size_bytes=512,
            compression_codec="audio/ogg;codecs=opus",
        )
        job_id = repo.enqueue_media_transcription_job(
            workspace_id=workspace_id,
            media_id=media_id,
            title="meeting.mp3",
            use_llm=False,
        )
        store.attach_task_media_job(task["id"], media_id, job_id)
    finally:
        store.close()

    class FakeASRClient:
        config = type(
            "Config",
            (),
            {"timeout_seconds": 30, "show_utterances": False},
        )()

        def transcribe_bytes(self, data, filename, content_type):
            return {
                "session_id": "session-1",
                "text": "会议转写结果",
                "utterances": [],
                "raw_result": {},
            }

    notification_calls = []

    def fail_notification(*, openid, task):
        notification_calls.append((openid, task["id"]))
        assert repo.get_job(job_id)["status"] == "completed"
        raise RuntimeError("WeChat is unavailable")

    monkeypatch.setattr(worker_module.StepFunASRClient, "from_env", lambda: FakeASRClient())
    monkeypatch.setattr(
        worker_module,
        "build_authorized_download_url",
        lambda object_name: f"https://download.example.test/{object_name}",
    )
    monkeypatch.setattr(worker_module, "request_bytes", lambda request, timeout_seconds: b"OGG")
    monkeypatch.setattr(worker_module, "send_task_complete_subscription", fail_notification)

    assert process_next_job(repo, job_types={"transcribe_media"}) is True
    assert process_next_job(repo, job_types={"send_site_notification"}) is True
    store = ASRSiteStore(repo)
    try:
        assert repo.get_job(job_id)["status"] == "completed"
        assert repo.get_media_record(media_id)["status"] == "processed"
        completed = store.get_task(task["id"])
        assert completed["status"] == "completed"
        assert completed["notify_on_complete"] is True
        assert completed["notification_template_id"] == "template-1"
        assert completed["notification_status"] == "failed"
        assert completed["notification_attempts"] == 1
        assert completed["notification_last_error"] == "WeChat is unavailable"
        assert notification_calls == [("openid-1", task["id"])]
    finally:
        store.close()
        repo.close()


def test_notification_outbox_recovers_and_duplicate_job_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("WECHAT_MINIAPP_APPID", "wx-test")
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    workspace_id = repo.create_workspace("ASR", "detailed_summary")
    local_path = tmp_path / "meeting.mp3"
    local_path.write_bytes(b"audio")
    store = ASRSiteStore(repo)
    try:
        user = store.get_or_create_wechat_user(
            appid="wx-test",
            openid="openid-1",
            unionid=None,
            session_key="session-key",
            signup_points=5,
        )
        task = create_pending_task(
            store,
            workspace_id,
            user["id"],
            local_path,
            task_id="task-recover",
        )
        store.mark_task_starting_with_points(
            task["id"],
            user["id"],
            notify_on_complete=True,
            notification_template_id="template-granted",
        )
        completed = store.update_task_status(task["id"], "completed")
        completed_at = completed["completed_at"]
        assert completed_at
        assert completed["notification_job_id"] is None
    finally:
        store.close()

    assert recover_pending_site_notifications(repo) == 1
    calls = []

    def send_notification(*, openid, task):
        calls.append((openid, task["notification_template_id"]))
        return True

    monkeypatch.setattr(worker_module, "send_task_complete_subscription", send_notification)
    assert process_next_job(repo, job_types={"send_site_notification"}) is True

    store = ASRSiteStore(repo)
    try:
        sent = store.get_task(task["id"])
        assert sent["notification_status"] == "sent"
        assert sent["notification_attempts"] == 1
        assert sent["notification_sent_at"]
        assert sent["completed_at"] == completed_at
        assert calls == [("openid-1", "template-granted")]
    finally:
        store.close()

    duplicate_job_id = repo.next_id("job")
    repo.conn.execute(
        """
        INSERT INTO jobs(id, type, status, payload, record_id, error)
        VALUES (?, 'send_site_notification', 'pending', ?, NULL, NULL)
        """,
        (duplicate_job_id, json.dumps({"task_id": task["id"]})),
    )
    repo.conn.commit()

    assert process_next_job(repo, job_types={"send_site_notification"}) is True
    assert repo.get_job(duplicate_job_id)["status"] == "completed"
    assert calls == [("openid-1", "template-granted")]
    repo.close()


def test_deleted_task_makes_queued_notification_a_noop(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    workspace_id = repo.create_workspace("ASR", "detailed_summary")
    local_path = tmp_path / "meeting.mp3"
    local_path.write_bytes(b"audio")
    store = ASRSiteStore(repo)
    try:
        user = store.create_user("Alice")
        store.add_points(user["id"], delta=5, kind="test")
        task = create_pending_task(
            store,
            workspace_id,
            user["id"],
            local_path,
            task_id="task-deleted",
        )
        store.mark_task_starting_with_points(
            task["id"],
            user["id"],
            notify_on_complete=True,
            notification_template_id="template-granted",
        )
        store.update_task_status(task["id"], "completed")
        notification_job_id = store.enqueue_task_notification(task["id"])
        assert notification_job_id
        store.delete_task(task["id"])
    finally:
        store.close()

    monkeypatch.setattr(
        worker_module,
        "send_task_complete_subscription",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("notification must not send")),
    )
    assert process_next_job(repo, job_types={"send_site_notification"}) is True
    assert repo.get_job(notification_job_id)["status"] == "completed"
    repo.close()


def test_notification_schema_is_available_for_sqlite_and_postgres(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    store = ASRSiteStore(repo)
    try:
        columns = {
            row["name"]
            for row in store.conn.execute("PRAGMA table_info(site_asr_tasks)").fetchall()
        }
        assert "notify_on_complete" in columns
        assert {
            "notification_template_id",
            "notification_job_id",
            "notification_status",
            "notification_attempts",
            "notification_last_error",
            "notification_sent_at",
            "completed_at",
        } <= columns
    finally:
        store.close()
        repo.close()

    executed = []

    class FakeConn:
        def execute(self, statement, params=()):
            executed.append(statement.strip())
            return self

    postgres_store = ASRSiteStore.__new__(ASRSiteStore)
    postgres_store.backend = "postgres"
    postgres_store.conn = FakeConn()
    postgres_store._init_schema()

    assert any(
        "ADD COLUMN IF NOT EXISTS notify_on_complete BOOLEAN NOT NULL DEFAULT FALSE"
        in statement
        for statement in executed
    )
    assert any(
        "ADD COLUMN IF NOT EXISTS notification_status TEXT NOT NULL DEFAULT 'disabled'"
        in statement
        for statement in executed
    )
    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "postgres"
        / "0004_site_task_notifications.sql"
    ).read_text(encoding="utf-8")
    assert "notify_on_complete BOOLEAN NOT NULL DEFAULT FALSE" in migration
    assert "notification_template_id TEXT NOT NULL DEFAULT ''" in migration
    assert "notification_status TEXT NOT NULL DEFAULT 'disabled'" in migration
    assert "completed_at TIMESTAMPTZ" in migration


def test_worker_runs_queue_maintenance_every_five_minutes(monkeypatch):
    monkeypatch.setenv("RECORDFLOW_STEPFUN_FILE_TIMEOUT_SECONDS", "1800")

    class WorkerStopped(Exception):
        pass

    class FakeRepo:
        def __init__(self):
            self.requeue_calls = []

        def requeue_stale_running_jobs(self, max_age_seconds=900):
            self.requeue_calls.append(max_age_seconds)
            return 0

    repo = FakeRepo()
    clock = {"now": 0.0}
    recovery_calls = []
    process_calls = 0

    def fake_process_next_job(repo, job_types=None):
        nonlocal process_calls
        process_calls += 1
        if process_calls == 1:
            return False
        raise WorkerStopped

    def fake_sleep(seconds):
        clock["now"] = 300.0

    monkeypatch.setattr(worker_module.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(worker_module, "process_next_job", fake_process_next_job)
    monkeypatch.setattr(
        worker_module,
        "recover_pending_site_notifications",
        lambda repo: recovery_calls.append(repo) or 0,
    )

    with pytest.raises(WorkerStopped):
        run_worker(repo=repo, poll_seconds=1.0, sleep=fake_sleep)

    assert repo.requeue_calls == [2100, 2100]
    assert recovery_calls == [repo, repo]
