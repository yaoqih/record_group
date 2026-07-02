from pathlib import Path

from recordflow_agent.eval_loader import load_eval_dataset
from recordflow_agent.sqlite_repository import SQLiteRepository


def test_load_eval_dataset_clears_database_and_enqueues_media(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    stale_workspace_id = repo.create_workspace("stale", "detailed_summary")
    assert stale_workspace_id

    eval_root = tmp_path / "eval"
    eval_root.mkdir()
    (eval_root / "a.mp3").write_bytes(b"audio-a")
    (eval_root / "b.m4a").write_bytes(b"audio-b")

    def fake_upload_media_to_b2(data, source_name, content_type):
        return {
            "bucket": "record-flow",
            "object_name": f"uploads/{source_name}",
            "file_id": "file-id",
            "content_type": content_type or "audio/mpeg",
            "size_bytes": len(data),
            "sha1": "sha1",
            "url": f"https://example.com/{source_name}",
            "public_url": f"https://example.com/{source_name}",
        }

    monkeypatch.setattr("recordflow_agent.eval_loader.upload_media_to_b2", fake_upload_media_to_b2)
    monkeypatch.setattr("recordflow_agent.eval_loader.process_next_job", lambda repo: False)

    result = load_eval_dataset(
        repo,
        eval_root,
        workspace_name="data/eval 在线导入",
        profile_name="detailed_summary",
        use_llm=True,
        reset=True,
    )

    assert result["workspace_id"]
    assert repo.list_workspaces()[0].name == "data/eval 在线导入"
    assert len(repo.list_media_records(result["workspace_id"])) == 2
    assert len(repo.list_records(result["workspace_id"])) == 0
