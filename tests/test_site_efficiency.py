import os

os.environ["RECORDFLOW_SKIP_DEFAULT_APP"] = "1"

from fastapi.testclient import TestClient

from recordflow_agent.api import create_app, create_site_session_token
from recordflow_agent.asr_site import AGREEMENT_VERSION, ASRSiteStore
from recordflow_agent.sqlite_repository import SQLiteRepository


def test_site_task_statuses_returns_lightweight_polling_payload(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    workspace_id = repo.create_workspace("ASR 网站", "detailed_summary")
    store = ASRSiteStore(repo)
    try:
        user = store.create_user("Alice")
        task = store.create_pending_task(
            task_id=store.next_id("task"),
            user_id=user["id"],
            workspace_id=workspace_id,
            title="meeting.mp3",
            source_name="meeting.mp3",
            content_type="audio/mpeg",
            original_size_bytes=1024,
            duration_seconds=30.0,
            points_cost=1,
            charge_basis="30.0s -> 1 points",
            agreement_version=AGREEMENT_VERSION,
            local_file_path=str(tmp_path / "meeting.mp3"),
        )
    finally:
        store.close()

    client = TestClient(create_app(repo))
    response = client.get(
        "/site/me/tasks/statuses",
        headers={"Authorization": f"Bearer {create_site_session_token(user['id'])}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["revision"]
    assert body["statuses"] == [
        {
            "id": task["id"],
            "status": "uploaded",
            "error": None,
            "updated_at": task["updated_at"],
        }
    ]
    assert "editable_utterances" not in body["statuses"][0]
    assert "raw_result" not in body["statuses"][0]
    repo.close()


def test_task_start_charges_points_once_when_repeated(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    workspace_id = repo.create_workspace("ASR 网站", "detailed_summary")
    store = ASRSiteStore(repo)
    try:
        user = store.create_user("Alice")
        store.add_points(user["id"], delta=5, kind="seed")
        task = store.create_pending_task(
            task_id=store.next_id("task"),
            user_id=user["id"],
            workspace_id=workspace_id,
            title="meeting.mp3",
            source_name="meeting.mp3",
            content_type="audio/mpeg",
            original_size_bytes=1024,
            duration_seconds=120.0,
            points_cost=2,
            charge_basis="120.0s -> 2 points",
            agreement_version=AGREEMENT_VERSION,
            local_file_path=str(tmp_path / "meeting.mp3"),
        )

        started = store.mark_task_starting_with_points(task["id"], user["id"])
        try:
            store.mark_task_starting_with_points(task["id"], user["id"])
        except ValueError as exc:
            assert "cannot be started" in str(exc)
        else:
            raise AssertionError("repeated task start should fail")

        assert started["status"] == "starting"
        assert store.get_user(user["id"])["points_balance"] == 3
        consume_entries = [
            item for item in store.list_point_ledger(user["id"]) if item["kind"] == "consume"
        ]
        assert len(consume_entries) == 1
        assert consume_entries[0]["delta"] == -2
    finally:
        store.close()
        repo.close()


def test_payment_confirmation_is_idempotent_and_atomic(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    store = ASRSiteStore(repo)
    try:
        user = store.create_user("Alice")
        store.create_payment_order(
            out_trade_no="pay-1",
            user_id=user["id"],
            points=100,
            amount_cents=100,
        )

        first_user, first_credited = store.mark_payment_order_paid(
            out_trade_no="pay-1",
            transaction_id="wx-1",
        )
        second_user, second_credited = store.mark_payment_order_paid(
            out_trade_no="pay-1",
            transaction_id="wx-1",
        )

        assert first_credited is True
        assert second_credited is False
        assert first_user["points_balance"] == 100
        assert second_user["points_balance"] == 100
        assert store.get_user(user["id"])["points_balance"] == 100
        recharge_entries = [
            item
            for item in store.list_point_ledger(user["id"])
            if item["kind"] == "wechatpay_recharge"
        ]
        assert len(recharge_entries) == 1
    finally:
        store.close()
        repo.close()


def test_login_requires_current_combined_agreement_and_privacy_notice(tmp_path, monkeypatch):
    monkeypatch.setenv("RECORDFLOW_ENABLE_DEV_LOGIN", "1")
    monkeypatch.setenv("RECORDFLOW_SESSION_SECRET", "session-secret")
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    client = TestClient(create_app(repo))

    rejected = client.post("/site/auth/dev/login", json={"nickname": "Alice"})
    accepted = client.post(
        "/site/auth/dev/login",
        json={
            "nickname": "Alice",
            "agreement_version": "v2",
            "agreement_accepted": True,
        },
    )
    me = client.get(
        "/site/me",
        headers={"Authorization": f"Bearer {accepted.json()['token']}"},
    )
    metadata = client.get("/site/agreement")

    assert rejected.status_code == 400
    assert "用户协议与隐私说明" in rejected.json()["detail"]
    assert accepted.status_code == 200
    assert accepted.json()["agreement"]["agreement_version"] == "v2"
    assert me.status_code == 200
    assert me.json()["agreement"] == {"version": "v2", "accepted": True}
    assert metadata.json()["agreement"]["title"] == "RecordFlow 用户协议与隐私说明"
    repo.close()


def test_legacy_login_can_be_temporarily_allowed_during_client_rollout(tmp_path, monkeypatch):
    monkeypatch.setenv("RECORDFLOW_ENABLE_DEV_LOGIN", "1")
    monkeypatch.setenv("RECORDFLOW_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("RECORDFLOW_REQUIRE_AGREEMENT", "false")
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    client = TestClient(create_app(repo))

    response = client.post("/site/auth/dev/login", json={"nickname": "Legacy"})

    assert response.status_code == 200
    assert response.json()["agreement"] is None
    repo.close()
