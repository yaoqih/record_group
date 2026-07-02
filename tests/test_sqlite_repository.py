from recordflow_agent.pipeline import process_record
from recordflow_agent.profiles import load_profile
from recordflow_agent.sqlite_repository import SQLiteRepository
from recordflow_agent.schemas import ObjectType


def test_sqlite_repository_persists_workspace_records_objects_and_changes(tmp_path):
    db_path = tmp_path / "recordflow.db"
    profile = load_profile("project_meeting")

    repo = SQLiteRepository(db_path)
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="meeting 1",
        text="决定先做文本导入 MVP。张三负责后端，周五前完成。",
    )
    repo.close()

    reopened = SQLiteRepository(db_path)
    objects = reopened.list_state_objects(workspace_id)
    changes = reopened.list_change_events(workspace_id)

    assert {obj.type for obj in objects} >= {ObjectType.DECISION, ObjectType.TASK}
    assert len(changes) >= 2
    assert reopened.workspaces[workspace_id].name == "RecordFlow product"
    reopened.close()


def test_sqlite_repository_persists_record_digest(tmp_path):
    db_path = tmp_path / "recordflow.db"
    profile = load_profile("project_meeting")

    repo = SQLiteRepository(db_path)
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    digest = process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="meeting 1",
        text="决定先做文本导入 MVP。张三负责后端，周五前完成。",
    )
    repo.close()

    reopened = SQLiteRepository(db_path)
    persisted = reopened.get_record_digest(digest.record_id)

    assert persisted["record_id"] == digest.record_id
    assert persisted["plan"]["engine"] == "top_down_digest_v1"
    assert persisted["sections"]
    assert persisted["extracted_objects"]
    reopened.close()


def test_sqlite_repository_enqueues_media_compression_job(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
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

    job_id = repo.enqueue_media_compression_job(
        workspace_id=workspace_id,
        media_id=media_id,
        title="meeting audio",
        use_llm=False,
    )
    job = repo.claim_next_job()

    assert job is not None
    assert job["id"] == job_id
    assert job["type"] == "compress_media"
    assert job["payload"]["workspace_id"] == workspace_id
    assert job["payload"]["media_id"] == media_id
    assert job["payload"]["title"] == "meeting audio"
    assert job["payload"]["use_llm"] is False
    repo.close()


def test_sqlite_repository_requeues_stale_running_jobs(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    job_id = repo.enqueue_record_job(
        workspace_id=workspace_id,
        title="meeting",
        text="张三负责后端，周五前完成。",
        use_llm=False,
    )
    claimed = repo.claim_next_job()
    repo.conn.execute(
        "UPDATE jobs SET updated_at = datetime('now', '-20 minutes') WHERE id = ?",
        (job_id,),
    )
    repo.conn.commit()

    count = repo.requeue_stale_running_jobs(max_age_seconds=60)
    job = repo.get_job(job_id)

    assert claimed["status"] == "running"
    assert count == 1
    assert job["status"] == "pending"
    assert "Requeued stale running job" in job["error"]
    repo.close()


def test_sqlite_repository_can_patch_state_object_and_archive_it(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="meeting 1",
        text="张三负责后端，周五前完成。",
    )
    task = next(obj for obj in repo.list_state_objects(workspace_id) if obj.type == ObjectType.TASK)

    patched, change = repo.patch_state_object(
        task.id,
        record_id="test_record",
        summary="更新后的任务摘要",
        status="closed",
    )
    archived, archive_change = repo.patch_state_object(
        task.id,
        record_id="test_record",
        status="archived",
    )

    assert patched.summary == "更新后的任务摘要"
    assert patched.status == "closed"
    assert change.change_type.value == "update"
    assert archived.status == "archived"
    assert archive_change.field_changes["status"]["to"] == "archived"
    repo.close()
