import os

import pytest

from recordflow_agent.pipeline import process_record
from recordflow_agent.postgres_repository import PostgresRepository
from recordflow_agent.profiles import load_profile
from recordflow_agent.schemas import ObjectType


@pytest.mark.skipif(
    not os.getenv("RECORDFLOW_TEST_DATABASE_URL"),
    reason="Set RECORDFLOW_TEST_DATABASE_URL to run Postgres repository integration tests.",
)
def test_postgres_repository_persists_workspace_records_objects_changes_and_jobs():
    repo = PostgresRepository(os.environ["RECORDFLOW_TEST_DATABASE_URL"])
    repo.reset_schema_for_tests()
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)

    digest = process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="meeting 1",
        text="决定先做文本导入 MVP。张三负责后端，周五前完成。",
    )
    job_id = repo.enqueue_record_job(
        workspace_id=workspace_id,
        title="meeting 2",
        text="风险是音频上传会拖慢进度。",
        use_llm=False,
    )
    media_id = repo.add_media_record(
        workspace_id=workspace_id,
        source_name="meeting.wav",
        stored_name="meeting.wav",
        url="https://img.blenet.top/file/record-flow/uploads/meeting.wav",
        public_url="https://f005.backblazeb2.com/file/record-flow/uploads/meeting.wav",
        object_name="uploads/meeting.wav",
        content_type="audio/wav",
        original_size_bytes=1000,
        compressed_size_bytes=1000,
        compression_codec="audio/wav",
    )
    compress_job_id = repo.enqueue_media_compression_job(
        workspace_id=workspace_id,
        media_id=media_id,
        title="meeting audio",
        use_llm=False,
    )
    claimed = repo.claim_next_job()
    second_claimed = repo.claim_next_job()

    objects = repo.list_state_objects(workspace_id)
    changes = repo.list_change_events(workspace_id)
    job = repo.get_job(job_id)
    persisted_digest = repo.get_record_digest(digest.record_id)

    assert {obj.type for obj in objects} >= {ObjectType.DECISION, ObjectType.TASK}
    assert len(changes) >= 2
    assert persisted_digest["record_id"] == digest.record_id
    assert persisted_digest["sections"]
    assert repo.workspaces[workspace_id].name == "RecordFlow product"
    assert claimed is not None
    assert claimed["id"] == job_id
    assert second_claimed is not None
    assert second_claimed["id"] == compress_job_id
    assert second_claimed["type"] == "compress_media"
    assert second_claimed["payload"]["media_id"] == media_id
    assert job["status"] == "running"
    assert repo.requeue_stale_running_jobs(max_age_seconds=0) >= 1
    assert repo.get_job(job_id)["status"] == "pending"
    repo.close()


def test_postgres_repository_uses_autocommit_to_avoid_idle_transactions(monkeypatch):
    class FakeConnection:
        def __init__(self) -> None:
            self.autocommit = None
            self.closed = False

        def close(self) -> None:
            self.closed = True

    fake_connection = FakeConnection()

    def fake_connect(database_url, row_factory):
        return fake_connection

    monkeypatch.setattr("recordflow_agent.postgres_repository.psycopg.connect", fake_connect)

    repo = PostgresRepository("postgresql://example", initialize=False)

    assert repo.conn.autocommit is True


def test_postgres_repository_reconnects_when_connection_is_closed(monkeypatch):
    class FakeConnection:
        def __init__(self) -> None:
            self.autocommit = None
            self.closed = False

        def close(self) -> None:
            self.closed = True

    connections: list[FakeConnection] = []

    def fake_connect(database_url, row_factory):
        connection = FakeConnection()
        connections.append(connection)
        return connection

    monkeypatch.setattr("recordflow_agent.postgres_repository.psycopg.connect", fake_connect)

    repo = PostgresRepository("postgresql://example", initialize=False)
    first = repo.conn
    first.closed = True
    second = repo.conn

    assert first is not second
    assert second.autocommit is True
    assert len(connections) == 2
