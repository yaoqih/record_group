from pathlib import Path

import pytest

from recordflow_agent.asr_site import AGREEMENT_VERSION, ASRSiteStore
from recordflow_agent.sqlite_repository import SQLiteRepository


def test_user_agreement_acceptance_is_versioned_and_idempotent(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    store = ASRSiteStore(repo)
    try:
        user = store.create_user("Alice")

        assert AGREEMENT_VERSION == "v2"
        assert store.has_accepted_user_agreement(user["id"]) is False

        first = store.accept_user_agreement(user["id"], client="miniprogram")
        repeated = store.accept_user_agreement(user["id"], client="web")
        legacy = store.accept_user_agreement(user["id"], "v1", "legacy-web")

        assert first == repeated
        assert first == {
            "user_id": user["id"],
            "agreement_version": "v2",
            "accepted_at": first["accepted_at"],
            "client": "miniprogram",
        }
        assert legacy["agreement_version"] == "v1"
        assert store.has_accepted_user_agreement(user["id"]) is True
        assert store.has_accepted_user_agreement(user["id"], "v1") is True
        assert store.has_accepted_user_agreement(user["id"], "v3") is False

        agreements = store.list_user_agreements(user["id"])
        assert {(item["agreement_version"], item["client"]) for item in agreements} == {
            ("v2", "miniprogram"),
            ("v1", "legacy-web"),
        }
        assert len(store.list_user_agreements()) == 2

        columns = {
            row["name"]
            for row in store.conn.execute("PRAGMA table_info(site_user_agreements)").fetchall()
        }
        indexes = {
            row["name"]
            for row in store.conn.execute("PRAGMA index_list(site_user_agreements)").fetchall()
        }
        assert columns == {"user_id", "agreement_version", "accepted_at", "client"}
        assert "idx_site_user_agreements_user_accepted" in indexes
    finally:
        store.close()
        repo.close()


def test_user_agreement_rejects_unknown_user_and_empty_version(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    store = ASRSiteStore(repo)
    try:
        user = store.create_user("Alice")

        with pytest.raises(KeyError):
            store.accept_user_agreement("missing-user")
        with pytest.raises(ValueError, match="agreement_version"):
            store.accept_user_agreement(user["id"], "  ")
        assert store.has_accepted_user_agreement(user["id"], "  ") is False
    finally:
        store.close()
        repo.close()


def test_postgres_runtime_schema_and_migration_include_user_agreements():
    executed: list[str] = []

    class FakeConn:
        def execute(self, statement, params=()):
            executed.append(statement.strip())
            return self

    store = ASRSiteStore.__new__(ASRSiteStore)
    store.backend = "postgres"
    store.conn = FakeConn()

    store._init_schema()

    assert any("CREATE TABLE IF NOT EXISTS site_user_agreements" in stmt for stmt in executed)
    assert any("PRIMARY KEY(user_id, agreement_version)" in stmt for stmt in executed)
    assert any("idx_site_user_agreements_user_accepted" in stmt for stmt in executed)

    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "postgres"
        / "0003_site_user_agreements.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS site_user_agreements" in migration
    assert "PRIMARY KEY(user_id, agreement_version)" in migration
    assert "idx_site_user_agreements_user_accepted" in migration


def test_delete_task_returns_lightweight_media_cleanup_metadata(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    workspace_id = repo.create_workspace("ASR", "detailed_summary")
    store = ASRSiteStore(repo)
    try:
        user = store.create_user("Alice")
        task = store.create_pending_task(
            task_id="task-delete",
            user_id=user["id"],
            workspace_id=workspace_id,
            title="meeting.mp3",
            source_name="meeting.mp3",
            content_type="audio/mpeg",
            original_size_bytes=1024,
            duration_seconds=30,
            points_cost=1,
            charge_basis="30.0s -> 1 points",
            agreement_version=AGREEMENT_VERSION,
            local_file_path=str(tmp_path / "meeting.mp3"),
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
            compression_codec="libopus",
        )
        store.attach_task_media_job(task["id"], media_id, "job-delete")
        store.save_correction(
            task["id"],
            [{"text": "large transcript payload", "start_time": 0, "end_time": 1000}],
        )

        statements: list[str] = []
        store.conn.set_trace_callback(statements.append)
        deleted = store.delete_task(task["id"])
        store.conn.set_trace_callback(None)

        assert deleted["id"] == task["id"]
        assert deleted["media_id"] == media_id
        assert deleted["object_name"] == "uploads/meeting.ogg"
        assert deleted["local_file_path"] == str(tmp_path / "meeting.mp3")
        assert "utterances" not in deleted
        with pytest.raises(KeyError):
            store.get_task(task["id"])
        assert repo.get_media_record(media_id)["object_name"] == "uploads/meeting.ogg"

        join_queries = [
            statement.lower()
            for statement in statements
            if "left join media_records" in statement.lower()
        ]
        assert len(join_queries) == 1
        assert "select *" not in join_queries[0]
        assert "editable_utterances" not in join_queries[0]
        assert "raw_result" not in join_queries[0]
    finally:
        store.close()
        repo.close()
