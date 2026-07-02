from recordflow_agent.pipeline import process_record
from recordflow_agent.profiles import load_profile
from recordflow_agent.sqlite_repository import SQLiteRepository


def test_review_queue_lists_and_updates_pending_review_items(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)

    process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="meeting 1",
        text="决定先做文本导入 MVP。风险是音频上传会拖慢进度。",
    )

    pending = repo.list_review_items(workspace_id)
    assert len(pending) == 2

    repo.set_review_status(pending[0].id, "accepted")
    remaining = repo.list_review_items(workspace_id)

    assert len(remaining) == 1
    assert remaining[0].id == pending[1].id
    repo.close()
