import os

os.environ["RECORDFLOW_SKIP_DEFAULT_APP"] = "1"

import pytest
from fastapi.testclient import TestClient

from recordflow_agent import api as api_module
from recordflow_agent import worker as worker_module
from recordflow_agent.api import create_app
from recordflow_agent.asr_site import AGREEMENT_VERSION, ASRSiteStore
from recordflow_agent.postgres_repository import PostgresRepository
from recordflow_agent.sqlite_repository import SQLiteRepository


def create_pending_task(repo, tmp_path, task_id, *, status="uploaded", with_media=False):
    workspace_id = repo.create_workspace(f"workspace-{task_id}", "project_meeting")
    local_path = tmp_path / f"{task_id}.mp3"
    local_path.write_bytes(b"audio")
    store = ASRSiteStore(repo)
    try:
        user = store.create_user(f"user-{task_id}")
        task = store.create_pending_task(
            task_id=task_id,
            user_id=user["id"],
            workspace_id=workspace_id,
            title=f"{task_id}.mp3",
            source_name=f"{task_id}.mp3",
            content_type="audio/mpeg",
            original_size_bytes=5,
            duration_seconds=30,
            points_cost=1,
            charge_basis="30.0s -> 1 points",
            agreement_version=AGREEMENT_VERSION,
            local_file_path=str(local_path),
        )
        media_id = None
        if with_media:
            media_id = repo.add_media_record(
                workspace_id=workspace_id,
                source_name=f"{task_id}.mp3",
                stored_name=f"{task_id}.ogg",
                url=f"https://cdn.example.com/{task_id}.ogg",
                public_url=f"https://public.example.com/{task_id}.ogg",
                object_name=f"uploads/{task_id}.ogg",
                content_type="audio/ogg",
                original_size_bytes=5,
                compressed_size_bytes=4,
                compression_codec="audio/ogg;codecs=opus",
            )
            store.attach_task_media_job(task_id, media_id, f"job-{task_id}")
            repo.update_media_status(
                media_id,
                "transcribed",
                transcript_text="sensitive transcript",
                utterances=[{"text": "sensitive transcript", "start_time": 0, "end_time": 1000}],
                raw_asr_result={"text": "sensitive transcript"},
            )
        if status != "uploaded":
            store.update_task_status(
                task_id,
                status,
                transcript_text="sensitive transcript" if with_media else None,
                raw_result={"text": "sensitive transcript"} if with_media else None,
            )
        return {
            "task_id": task_id,
            "user_id": user["id"],
            "workspace_id": workspace_id,
            "media_id": media_id,
            "local_path": local_path,
        }
    finally:
        store.close()


def test_uploaded_task_delete_removes_local_upload(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    created = create_pending_task(repo, tmp_path, "task-uploaded")
    client = TestClient(create_app(repo))

    response = client.delete(f"/site/tasks/{created['task_id']}")

    assert response.status_code == 200
    assert not created["local_path"].exists()
    store = ASRSiteStore(repo)
    try:
        with pytest.raises(KeyError):
            store.get_task(created["task_id"])
    finally:
        store.close()
        repo.close()


@pytest.mark.parametrize("status", ["starting", "queued", "transcribing"])
def test_active_task_delete_is_rejected_without_cleaning_files(tmp_path, status):
    repo = SQLiteRepository(tmp_path / f"{status}.db")
    created = create_pending_task(repo, tmp_path, f"task-{status}", status=status)
    client = TestClient(create_app(repo))

    response = client.delete(f"/site/tasks/{created['task_id']}")

    assert response.status_code == 409
    assert created["local_path"].exists()
    store = ASRSiteStore(repo)
    try:
        assert store.get_task(created["task_id"])["status"] == status
    finally:
        store.close()
        repo.close()


@pytest.mark.parametrize("status", ["completed", "failed", "expired"])
def test_finished_task_delete_removes_object_task_and_media_payload(tmp_path, monkeypatch, status):
    repo = SQLiteRepository(tmp_path / f"{status}.db")
    created = create_pending_task(
        repo,
        tmp_path,
        f"task-{status}",
        status=status,
        with_media=True,
    )
    created["local_path"].unlink()
    events = []
    original_delete_task = ASRSiteStore.delete_task
    original_delete_media_record = repo.delete_media_record

    def delete_object(object_name):
        events.append(("object", object_name))

    def delete_task(store, task_id):
        events.append(("task", task_id))
        return original_delete_task(store, task_id)

    def delete_media_record(media_id):
        events.append(("media", media_id))
        return original_delete_media_record(media_id)

    monkeypatch.setattr(api_module, "delete_media_from_b2", delete_object)
    monkeypatch.setattr(ASRSiteStore, "delete_task", delete_task)
    monkeypatch.setattr(repo, "delete_media_record", delete_media_record)
    client = TestClient(create_app(repo))

    response = client.delete(f"/site/tasks/{created['task_id']}")

    assert response.status_code == 200
    assert events == [
        ("object", f"uploads/{created['task_id']}.ogg"),
        ("task", created["task_id"]),
        ("media", created["media_id"]),
    ]
    store = ASRSiteStore(repo)
    try:
        with pytest.raises(KeyError):
            store.get_task(created["task_id"])
        with pytest.raises(KeyError):
            repo.get_media_record(created["media_id"])
    finally:
        store.close()
        repo.close()


def test_object_delete_failure_keeps_task_and_media_payload(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    created = create_pending_task(
        repo,
        tmp_path,
        "task-object-failure",
        status="completed",
        with_media=True,
    )
    created["local_path"].unlink()

    def fail_delete(_object_name):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(api_module, "delete_media_from_b2", fail_delete)
    client = TestClient(create_app(repo))

    response = client.delete(f"/site/tasks/{created['task_id']}")

    assert response.status_code == 502
    assert "任务未删除" in response.json()["detail"]
    store = ASRSiteStore(repo)
    try:
        assert store.get_task(created["task_id"])["status"] == "completed"
        media = repo.get_media_record(created["media_id"])
        assert media["transcript_text"] == "sensitive transcript"
        assert media["raw_asr_result"] == {"text": "sensitive transcript"}
    finally:
        store.close()
        repo.close()


def test_site_transcription_does_not_create_generic_digest_copy(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    created = create_pending_task(
        repo,
        tmp_path,
        "task-site-transcription",
        status="queued",
        with_media=True,
    )
    job_id = repo.enqueue_media_transcription_job(
        workspace_id=created["workspace_id"],
        media_id=created["media_id"],
        title="site recording",
        use_llm=False,
    )
    store = ASRSiteStore(repo)
    try:
        store.attach_task_media_job(created["task_id"], created["media_id"], job_id)
    finally:
        store.close()

    class FakeASRClient:
        config = type("Config", (), {"timeout_seconds": 30, "show_utterances": False})()

        def transcribe_bytes(self, data, filename, content_type):
            return {
                "task_id": "asr-task-1",
                "text": "site transcript",
                "raw_result": {"text": "site transcript"},
            }

    monkeypatch.setattr(worker_module.StepFunASRClient, "from_env", classmethod(lambda cls: FakeASRClient()))
    monkeypatch.setattr(worker_module, "build_authorized_download_url", lambda object_name: "https://download")
    monkeypatch.setattr(worker_module, "request_bytes", lambda request, timeout_seconds: b"OGG")

    def fail_process_record(**kwargs):
        raise AssertionError("site ASR must not create a generic digest copy")

    monkeypatch.setattr(worker_module, "process_record", fail_process_record)

    assert worker_module.process_next_job(repo, job_types={"transcribe_media"}) is True
    assert repo.get_job(job_id)["record_id"] == created["media_id"]
    assert repo.get_media_record(created["media_id"])["status"] == "processed"
    assert repo.list_records(created["workspace_id"]) == []
    assert repo.list_state_objects(created["workspace_id"]) == []
    store = ASRSiteStore(repo)
    try:
        assert store.get_task(created["task_id"])["status"] == "completed"
    finally:
        store.close()
        repo.close()


def test_postgres_repository_deletes_media_record_with_returning(monkeypatch):
    class FakeCursor:
        def fetchone(self):
            return {"id": "media-1"}

    class FakeConnection:
        def __init__(self):
            self.autocommit = False
            self.closed = False
            self.executed = []

        def execute(self, statement, params=()):
            self.executed.append((statement, params))
            return FakeCursor()

        def close(self):
            self.closed = True

    connection = FakeConnection()
    monkeypatch.setattr(
        "recordflow_agent.postgres_repository.psycopg.connect",
        lambda database_url, row_factory: connection,
    )
    repo = PostgresRepository("postgresql://example", initialize=False)

    repo.delete_media_record("media-1")

    assert connection.executed == [
        ("DELETE FROM media_records WHERE id = %s RETURNING id", ("media-1",))
    ]
