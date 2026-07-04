import base64
import json
import os
os.environ["RECORDFLOW_SKIP_DEFAULT_APP"] = "1"

from fastapi.testclient import TestClient

from recordflow_agent.api import create_app
from recordflow_agent.asr_site import ASRSiteStore
from recordflow_agent.sqlite_repository import SQLiteRepository
from recordflow_agent import api as api_module
from recordflow_agent import worker as worker_module


def fake_b2_upload(data, source_name, content_type):
    return {
        "url": "https://cdn.example.com/audio.ogg",
        "public_url": "https://public.example.com/audio.ogg",
        "object_name": "uploads/test/audio.ogg",
        "content_type": content_type or "audio/ogg",
        "size_bytes": len(data),
    }


def drain_site_task_jobs(repo):
    prepared = worker_module.process_next_job(repo, job_types={"prepare_site_task"})
    transcribed = worker_module.process_next_job(repo, job_types={"transcribe_media"})
    return prepared, transcribed


def test_site_can_create_user_and_recharge_points(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)

    create_response = client.post("/site/users", json={"name": "Alice"})
    user_id = create_response.json()["user"]["id"]
    recharge_response = client.post(
        f"/site/users/{user_id}/recharge",
        json={"points": 25, "note": "seed"},
    )
    users_response = client.get("/site/users")

    assert create_response.status_code == 200
    assert recharge_response.status_code == 200
    assert recharge_response.json()["user"]["points_balance"] == 25
    assert users_response.json()["users"][0]["name"] == "Alice"
    repo.close()


def test_site_wechat_login_creates_user_and_session(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    monkeypatch.setenv("WECHAT_MINIAPP_APPID", "wx-test")
    monkeypatch.setenv("WECHAT_MINIAPP_SECRET", "secret")
    monkeypatch.setenv("RECORDFLOW_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("RECORDFLOW_MINIAPP_SIGNUP_POINTS", "3")
    monkeypatch.setattr(
        api_module,
        "exchange_wechat_code_for_session",
        lambda appid, secret, code: {
            "openid": "openid-1",
            "unionid": "unionid-1",
            "session_key": "session-key-1",
        },
    )
    app = create_app(repo)
    client = TestClient(app)

    login = client.post("/site/auth/wechat/login", json={"code": "login-code", "nickname": "Alice"})
    token = login.json()["token"]
    me = client.get("/site/me", headers={"Authorization": f"Bearer {token}"})
    second_login = client.post("/site/auth/wechat/login", json={"code": "login-code-2"})

    assert login.status_code == 200
    assert login.json()["user"]["name"] == "Alice"
    assert login.json()["user"]["points_balance"] == 3
    assert me.status_code == 200
    assert me.json()["user"]["id"] == login.json()["user"]["id"]
    assert second_login.status_code == 200
    assert second_login.json()["user"]["id"] == login.json()["user"]["id"]
    assert second_login.json()["user"]["points_balance"] == 3
    repo.close()


def test_site_dev_login_creates_local_user(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    monkeypatch.setenv("RECORDFLOW_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("RECORDFLOW_MINIAPP_SIGNUP_POINTS", "5")
    app = create_app(repo)
    client = TestClient(app)

    login = client.post("/site/auth/dev/login", json={"nickname": "Local"})
    token = login.json()["token"]
    me = client.get("/site/me", headers={"Authorization": f"Bearer {token}"})

    assert login.status_code == 200
    assert login.json()["user"]["name"] == "Local"
    assert login.json()["user"]["points_balance"] == 5
    assert me.status_code == 200
    assert me.json()["user"]["id"] == login.json()["user"]["id"]
    repo.close()


def test_site_me_task_upload_uses_session_user(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    monkeypatch.setenv("WECHAT_MINIAPP_APPID", "wx-test")
    monkeypatch.setenv("WECHAT_MINIAPP_SECRET", "secret")
    monkeypatch.setenv("RECORDFLOW_SESSION_SECRET", "session-secret")
    monkeypatch.setattr(
        api_module,
        "exchange_wechat_code_for_session",
        lambda appid, secret, code: {
            "openid": "openid-1",
            "session_key": "session-key-1",
        },
    )
    monkeypatch.setattr(api_module, "probe_media_duration_seconds", lambda file_path: 12.0)
    app = create_app(repo)
    client = TestClient(app)

    login = client.post("/site/auth/wechat/login", json={"code": "login-code"})
    token = login.json()["token"]
    response = client.post(
        "/site/me/tasks",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("call.mp3", b"fake-mp3-data", "audio/mpeg")},
    )
    tasks = client.get("/site/me/tasks", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["task"]["user_id"] == login.json()["user"]["id"]
    assert tasks.status_code == 200
    assert tasks.json()["tasks"][0]["id"] == response.json()["task"]["id"]
    repo.close()


def test_site_me_wechatpay_recharge_requires_configuration(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)

    monkeypatch.setenv("WECHAT_MINIAPP_APPID", "wx-test")
    monkeypatch.setenv("RECORDFLOW_SESSION_SECRET", "session-secret")
    monkeypatch.delenv("WECHAT_PAY_MCH_ID", raising=False)
    monkeypatch.delenv("WECHAT_PAY_MCH_SERIAL_NO", raising=False)
    monkeypatch.delenv("WECHAT_PAY_MCH_PRIVATE_KEY_PATH", raising=False)
    monkeypatch.delenv("WECHAT_PAY_NOTIFY_URL", raising=False)

    store = ASRSiteStore(repo)
    try:
        user = store.get_or_create_wechat_user(
            appid="wx-test",
            openid="openid-1",
            unionid=None,
            session_key="session-key",
            default_name="Alice",
        )
    finally:
        store.close()
    token = api_module.create_site_session_token(user["id"])

    response = client.post(
        "/site/me/recharge/wechatpay",
        json={"points": 100},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    assert "微信支付未配置" in response.json()["detail"]
    repo.close()


def test_pending_upload_path_uses_configured_root(tmp_path, monkeypatch):
    from recordflow_agent.asr_site import pending_upload_path

    monkeypatch.setenv("RECORDFLOW_PENDING_UPLOAD_ROOT", str(tmp_path / "oss" / "staging"))

    path = pending_upload_path("task_1", "../客户录音.mp3")

    assert path.parent == tmp_path / "oss" / "staging"
    assert path.name == "task_1-客户录音.mp3"
    assert path.parent.exists()


def test_site_me_direct_upload_init_returns_cos_post_policy(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    monkeypatch.setenv("RECORDFLOW_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("TENCENTCLOUD_SECRET_ID", "cos-secret-id")
    monkeypatch.setenv("TENCENTCLOUD_SECRET_KEY", "cos-secret-key")
    monkeypatch.setenv("RECORDFLOW_PENDING_UPLOAD_ROOT", str(tmp_path / "pending"))
    monkeypatch.setenv(
        "RECORDFLOW_PENDING_UPLOAD_PUBLIC_BASE_URL",
        "https://record-1439403413.cos.ap-shanghai.myqcloud.com/staging/pending",
    )
    app = create_app(repo)
    client = TestClient(app)
    user = client.post("/site/users", json={"name": "Alice"}).json()["user"]
    token = api_module.create_site_session_token(user["id"])

    response = client.post(
        "/site/me/tasks/direct-upload/init",
        json={"source_name": "客户录音.mp3", "size_bytes": 1024},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    upload = body["upload"]
    form_data = upload["form_data"]
    policy = json_loads_base64(form_data["policy"])
    assert upload["url"] == "https://record-1439403413.cos.ap-shanghai.myqcloud.com"
    assert upload["object_key"].startswith("staging/pending/")
    assert form_data["key"] == upload["object_key"]
    assert form_data["q-ak"] == "cos-secret-id"
    assert policy["conditions"][0] == {"bucket": "record-1439403413"}
    assert {"key": upload["object_key"]} in policy["conditions"]
    assert ["content-length-range", 1, api_module.SITE_TASK_MAX_AUDIO_BYTES] in policy["conditions"]
    repo.close()


def test_site_me_direct_upload_init_can_use_public_write_cos(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    monkeypatch.setenv("RECORDFLOW_SESSION_SECRET", "session-secret")
    monkeypatch.delenv("TENCENTCLOUD_SECRET_ID", raising=False)
    monkeypatch.delenv("TENCENTCLOUD_SECRET_KEY", raising=False)
    monkeypatch.setenv("RECORDFLOW_COS_DIRECT_UPLOAD_PUBLIC_WRITE", "true")
    monkeypatch.setenv("RECORDFLOW_PENDING_UPLOAD_ROOT", str(tmp_path / "pending"))
    monkeypatch.setenv(
        "RECORDFLOW_PENDING_UPLOAD_PUBLIC_BASE_URL",
        "https://record-1439403413.cos.ap-shanghai.myqcloud.com/staging/pending",
    )
    app = create_app(repo)
    client = TestClient(app)
    user = client.post("/site/users", json={"name": "Alice"}).json()["user"]
    token = api_module.create_site_session_token(user["id"])

    response = client.post(
        "/site/me/tasks/direct-upload/init",
        json={"source_name": "call.mp3", "size_bytes": 1024},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    upload = response.json()["upload"]
    assert upload["auth"] == "public-write"
    assert upload["form_data"]["key"] == upload["object_key"]
    assert "policy" not in upload["form_data"]
    assert "q-signature" not in upload["form_data"]
    repo.close()


def test_site_me_direct_upload_complete_creates_task_from_pending_mount(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    pending_root = tmp_path / "pending"
    monkeypatch.setenv("RECORDFLOW_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("TENCENTCLOUD_SECRET_ID", "cos-secret-id")
    monkeypatch.setenv("TENCENTCLOUD_SECRET_KEY", "cos-secret-key")
    monkeypatch.setenv("RECORDFLOW_PENDING_UPLOAD_ROOT", str(pending_root))
    monkeypatch.setenv(
        "RECORDFLOW_PENDING_UPLOAD_PUBLIC_BASE_URL",
        "https://record-1439403413.cos.ap-shanghai.myqcloud.com/staging/pending",
    )
    monkeypatch.setattr(api_module, "probe_media_duration_seconds", lambda file_path: 61.0)
    app = create_app(repo)
    client = TestClient(app)
    user = client.post("/site/users", json={"name": "Alice"}).json()["user"]
    token = api_module.create_site_session_token(user["id"])
    init = client.post(
        "/site/me/tasks/direct-upload/init",
        json={"source_name": "客户录音.mp3", "size_bytes": 14},
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    local_name = init["upload"]["object_key"].rsplit("/", 1)[-1]
    pending_root.mkdir(parents=True, exist_ok=True)
    (pending_root / local_name).write_bytes(b"fake-mp3-data")

    complete = client.post(
        "/site/me/tasks/direct-upload/complete",
        json={
            "upload_token": init["upload_token"],
            "object_key": init["upload"]["object_key"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert complete.status_code == 200
    task = complete.json()["task"]
    assert task["user_id"] == user["id"]
    assert task["status"] == "uploaded"
    assert task["source_name"] == "客户录音.mp3"
    assert task["duration_seconds"] == 61.0
    assert task["points_cost"] == 2
    assert task["local_file_path"] == str(pending_root / local_name)
    repo.close()


def test_site_me_direct_upload_complete_waits_for_mount_visibility(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    monkeypatch.setenv("RECORDFLOW_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("TENCENTCLOUD_SECRET_ID", "cos-secret-id")
    monkeypatch.setenv("TENCENTCLOUD_SECRET_KEY", "cos-secret-key")
    monkeypatch.setenv("RECORDFLOW_PENDING_UPLOAD_ROOT", str(tmp_path / "pending"))
    monkeypatch.setenv(
        "RECORDFLOW_PENDING_UPLOAD_PUBLIC_BASE_URL",
        "https://record-1439403413.cos.ap-shanghai.myqcloud.com/staging/pending",
    )
    app = create_app(repo)
    client = TestClient(app)
    user = client.post("/site/users", json={"name": "Alice"}).json()["user"]
    token = api_module.create_site_session_token(user["id"])
    init = client.post(
        "/site/me/tasks/direct-upload/init",
        json={"source_name": "call.mp3", "size_bytes": 14},
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    response = client.post(
        "/site/me/tasks/direct-upload/complete",
        json={"upload_token": init["upload_token"], "object_key": init["upload"]["object_key"]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409
    assert "visible" in response.json()["detail"]
    repo.close()


def test_site_me_direct_upload_complete_rejects_other_user_token(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    monkeypatch.setenv("RECORDFLOW_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("TENCENTCLOUD_SECRET_ID", "cos-secret-id")
    monkeypatch.setenv("TENCENTCLOUD_SECRET_KEY", "cos-secret-key")
    monkeypatch.setenv("RECORDFLOW_PENDING_UPLOAD_ROOT", str(tmp_path / "pending"))
    monkeypatch.setenv(
        "RECORDFLOW_PENDING_UPLOAD_PUBLIC_BASE_URL",
        "https://record-1439403413.cos.ap-shanghai.myqcloud.com/staging/pending",
    )
    app = create_app(repo)
    client = TestClient(app)
    alice = client.post("/site/users", json={"name": "Alice"}).json()["user"]
    bob = client.post("/site/users", json={"name": "Bob"}).json()["user"]
    alice_token = api_module.create_site_session_token(alice["id"])
    bob_token = api_module.create_site_session_token(bob["id"])
    init = client.post(
        "/site/me/tasks/direct-upload/init",
        json={"source_name": "call.mp3", "size_bytes": 14},
        headers={"Authorization": f"Bearer {alice_token}"},
    ).json()

    response = client.post(
        "/site/me/tasks/direct-upload/complete",
        json={"upload_token": init["upload_token"], "object_key": init["upload"]["object_key"]},
        headers={"Authorization": f"Bearer {bob_token}"},
    )

    assert response.status_code == 403
    repo.close()


def json_loads_base64(value: str) -> dict:
    return json.loads(base64.b64decode(value).decode("utf-8"))


def test_site_me_wechatpay_confirm_queries_order_and_credits_once(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)

    monkeypatch.setenv("WECHAT_MINIAPP_APPID", "wx-test")
    monkeypatch.setenv("RECORDFLOW_SESSION_SECRET", "session-secret")
    monkeypatch.setattr(
        api_module,
        "query_wechatpay_order",
        lambda out_trade_no: {
            "out_trade_no": out_trade_no,
            "transaction_id": "wx-tx-1",
            "trade_state": "SUCCESS",
            "amount": {"total": 100},
        },
    )

    store = ASRSiteStore(repo)
    try:
        user = store.get_or_create_wechat_user(
            appid="wx-test",
            openid="openid-1",
            unionid=None,
            session_key="session-key",
            default_name="Alice",
        )
        store.create_payment_order(
            out_trade_no="rf_test_1",
            user_id=user["id"],
            points=100,
            amount_cents=100,
        )
    finally:
        store.close()
    token = api_module.create_site_session_token(user["id"])

    first = client.post(
        "/site/me/recharge/wechatpay/confirm",
        json={"out_trade_no": "rf_test_1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    second = client.post(
        "/site/me/recharge/wechatpay/confirm",
        json={"out_trade_no": "rf_test_1"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert first.status_code == 200
    assert first.json()["credited"] is True
    assert first.json()["user"]["points_balance"] == 100
    assert second.status_code == 200
    assert second.json()["credited"] is False
    store = ASRSiteStore(repo)
    try:
        assert store.get_user(user["id"])["points_balance"] == 100
    finally:
        store.close()
        repo.close()


def test_wechatpay_recharge_package_allows_custom_range():
    custom = api_module.recharge_package_or_400(123)

    assert custom["points"] == 123
    assert custom["amount_cents"] == 123


def test_site_store_initializes_schema_once_per_target(tmp_path, monkeypatch):
    db_path = tmp_path / "recordflow.db"
    repo = SQLiteRepository(db_path)
    init_calls: list[tuple[str, str]] = []
    original_init_schema = ASRSiteStore._init_schema

    ASRSiteStore._schema_ready_targets.clear()

    def counted_init_schema(self):
        init_calls.append((self.backend, self.target))
        return original_init_schema(self)

    monkeypatch.setattr(ASRSiteStore, "_init_schema", counted_init_schema)

    first = ASRSiteStore(repo)
    second = ASRSiteStore(repo)
    try:
        assert len(init_calls) == 1
        assert init_calls[0][0] == "sqlite"
    finally:
        first.close()
        second.close()
        repo.close()


def test_postgres_schema_init_preserves_legacy_raw_result_default():
    executed: list[str] = []

    class FakeConn:
        def execute(self, statement, params=()):
            executed.append(statement.strip())
            return self

    store = ASRSiteStore.__new__(ASRSiteStore)
    store.backend = "postgres"
    store.conn = FakeConn()

    store._init_schema()

    assert any("ADD COLUMN IF NOT EXISTS raw_result JSONB DEFAULT '{}'::jsonb" in stmt for stmt in executed)
    assert any("ALTER COLUMN raw_result SET DEFAULT '{}'::jsonb" in stmt for stmt in executed)


def test_site_submit_task_creates_job_and_deducts_points(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)

    monkeypatch.setattr(api_module, "probe_media_duration_seconds", lambda file_path: 61.0)

    user = client.post("/site/users", json={"name": "Alice"}).json()["user"]
    client.post(f"/site/users/{user['id']}/recharge", json={"points": 10})

    response = client.post(
        f"/site/users/{user['id']}/tasks",
        files={"file": ("call.mp3", b"fake-mp3-data", "audio/mpeg")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["task"]["status"] == "uploaded"
    assert body["task"]["points_cost"] == 2
    assert body["task"]["duration_seconds"] == 61.0

    store = ASRSiteStore(tmp_path / "recordflow.db")
    try:
        saved_user = store.get_user(user["id"])
        saved_task = store.get_task(body["task"]["id"])
        assert saved_user["points_balance"] == 10
        assert saved_task["media_id"] is None
        assert saved_task["local_file_path"]
    finally:
        store.close()
        repo.close()


def test_site_submit_task_returns_readable_error_when_ffprobe_is_missing(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)

    user = client.post("/site/users", json={"name": "Alice"}).json()["user"]
    client.post(f"/site/users/{user['id']}/recharge", json={"points": 10})

    def raise_missing_binary(file_path):
        raise FileNotFoundError("ffprobe")

    monkeypatch.setattr(api_module, "probe_media_duration_seconds", raise_missing_binary)

    response = client.post(
        f"/site/users/{user['id']}/tasks",
        files={"file": ("call.mp3", b"fake-mp3-data", "audio/mpeg")},
    )

    assert response.status_code == 503
    assert "ffprobe" in response.json()["detail"]
    repo.close()


def test_site_submit_task_rejects_video_uploads(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)

    user = client.post("/site/users", json={"name": "Alice"}).json()["user"]

    response = client.post(
        f"/site/users/{user['id']}/tasks",
        files={"file": ("clip.mp4", b"fake-video-data", "video/mp4")},
    )

    assert response.status_code == 400
    assert "仅支持提交音频文件" in response.json()["detail"]
    repo.close()


def test_site_submit_task_rejects_audio_larger_than_200mb(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)

    user = client.post("/site/users", json={"name": "Alice"}).json()["user"]

    response = client.post(
        f"/site/users/{user['id']}/tasks",
        files={"file": ("large.mp3", b"x" * (api_module.SITE_TASK_MAX_AUDIO_BYTES + 1), "audio/mpeg")},
    )

    assert response.status_code == 413
    assert "200MB" in response.json()["detail"]
    repo.close()


def test_worker_completes_site_task_and_persists_transcript(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)

    monkeypatch.setattr(api_module, "probe_media_duration_seconds", lambda file_path: 61.0)
    monkeypatch.setattr(worker_module, "compress_audio_for_asr", lambda data, filename, content_type: b"OGGDATA")
    monkeypatch.setattr(
        worker_module,
        "upload_media_to_b2",
        fake_b2_upload,
    )
    monkeypatch.setattr(worker_module, "build_authorized_download_url", lambda object_name: "https://download")
    monkeypatch.setattr(worker_module, "request_bytes", lambda request, timeout_seconds: b"OGGDATA")

    class FakeASRClient:
        config = type("Config", (), {"timeout_seconds": 30, "show_utterances": False})()

        def transcribe_bytes(self, data, filename, content_type=None):
            return {
                "task_id": "stepaudio-task-1",
                "text": "你好，这是一段测试转写。",
                "utterances": [],
                "raw_result": {"text": "你好，这是一段测试转写。"},
            }

    monkeypatch.setattr(worker_module.StepFunASRClient, "from_env", classmethod(lambda cls: FakeASRClient()))

    user = client.post("/site/users", json={"name": "Alice"}).json()["user"]
    client.post(f"/site/users/{user['id']}/recharge", json={"points": 10})
    submit = client.post(
        f"/site/users/{user['id']}/tasks",
        files={"file": ("call.mp3", b"fake-mp3-data", "audio/mpeg")},
    ).json()
    start = client.post(
        f"/site/tasks/{submit['task']['id']}/start",
        json={"confirm_points": True},
    ).json()

    processed = drain_site_task_jobs(repo)
    task_response = client.get(f"/site/tasks/{submit['task']['id']}/editor")

    assert start["task"]["status"] == "starting"
    assert processed == (True, True)
    assert task_response.status_code == 200
    assert task_response.json()["task"]["status"] == "completed"
    assert task_response.json()["editor"]["utterances"][0]["text"] == "你好，这是一段测试转写。"
    repo.close()


def test_site_task_detail_exposes_media_and_utterances_for_editor(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)

    monkeypatch.setattr(api_module, "probe_media_duration_seconds", lambda file_path: 61.0)
    monkeypatch.setattr(worker_module, "compress_audio_for_asr", lambda data, filename, content_type: b"OGGDATA")
    monkeypatch.setattr(
        worker_module,
        "upload_media_to_b2",
        fake_b2_upload,
    )
    monkeypatch.setattr(worker_module, "build_authorized_download_url", lambda object_name: "https://download")
    monkeypatch.setattr(worker_module, "request_bytes", lambda request, timeout_seconds: b"OGGDATA")

    class FakeASRClient:
        config = type("Config", (), {"timeout_seconds": 30, "show_utterances": True})()

        def transcribe_url(self, url, content_type=None):
            return {
                "task_id": "stepaudio-task-1",
                "text": "你好，这是一段测试转写。",
                "utterances": [
                    {"text": "你好", "start_time": 0, "end_time": 500},
                    {"text": "这是一段测试转写。", "start_time": 500, "end_time": 1800},
                ],
                "raw_result": {
                    "result": [
                        {
                            "text": "你好，这是一段测试转写。",
                            "utterances": [
                                {"text": "你好", "start_time": 0, "end_time": 500},
                                {"text": "这是一段测试转写。", "start_time": 500, "end_time": 1800},
                            ],
                        }
                    ]
                },
            }

    monkeypatch.setattr(worker_module.StepFunASRClient, "from_env", classmethod(lambda cls: FakeASRClient()))

    user = client.post("/site/users", json={"name": "Alice"}).json()["user"]
    client.post(f"/site/users/{user['id']}/recharge", json={"points": 10})
    submit = client.post(
        f"/site/users/{user['id']}/tasks",
        files={"file": ("call.mp3", b"fake-mp3-data", "audio/mpeg")},
    ).json()
    client.post(f"/site/tasks/{submit['task']['id']}/start", json={"confirm_points": True})
    drain_site_task_jobs(repo)

    task_response = client.get(f"/site/tasks/{submit['task']['id']}/editor")

    assert task_response.status_code == 200
    body = task_response.json()
    assert body["task"]["media"]["public_url"] == "https://public.example.com/audio.ogg"
    assert "raw_asr_result" not in body["task"]["media"]
    assert "utterances" not in body["task"]["media"]
    assert "transcript_text" not in body["task"]["media"]
    assert body["editor"]["utterances"][0]["text"] == "你好"
    assert body["editor"]["utterances"][1]["start_time"] == 500
    repo.close()


def test_site_task_correction_persists_editable_utterances(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)

    monkeypatch.setattr(api_module, "probe_media_duration_seconds", lambda file_path: 61.0)
    monkeypatch.setattr(worker_module, "compress_audio_for_asr", lambda data, filename, content_type: b"OGGDATA")
    monkeypatch.setattr(
        worker_module,
        "upload_media_to_b2",
        fake_b2_upload,
    )
    monkeypatch.setattr(worker_module, "build_authorized_download_url", lambda object_name: "https://download")
    monkeypatch.setattr(worker_module, "request_bytes", lambda request, timeout_seconds: b"OGGDATA")

    class FakeASRClient:
        config = type("Config", (), {"timeout_seconds": 30, "show_utterances": True})()

        def transcribe_url(self, url, content_type=None):
            return {
                "task_id": "stepaudio-task-1",
                "text": "你好，这是一段测试转写。",
                "utterances": [
                    {"text": "你好", "start_time": 0, "end_time": 500},
                    {"text": "这是一段测试转写。", "start_time": 500, "end_time": 1800},
                ],
                "raw_result": {
                    "result": [
                        {
                            "text": "你好，这是一段测试转写。",
                            "utterances": [
                                {"text": "你好", "start_time": 0, "end_time": 500},
                                {"text": "这是一段测试转写。", "start_time": 500, "end_time": 1800},
                            ],
                        }
                    ]
                },
            }

    monkeypatch.setattr(worker_module.StepFunASRClient, "from_env", classmethod(lambda cls: FakeASRClient()))

    user = client.post("/site/users", json={"name": "Alice"}).json()["user"]
    client.post(f"/site/users/{user['id']}/recharge", json={"points": 10})
    submit = client.post(
        f"/site/users/{user['id']}/tasks",
        files={"file": ("call.mp3", b"fake-mp3-data", "audio/mpeg")},
    ).json()
    client.post(f"/site/tasks/{submit['task']['id']}/start", json={"confirm_points": True})
    drain_site_task_jobs(repo)

    save = client.post(
        f"/site/tasks/{submit['task']['id']}/correction",
        json={
            "utterances": [
                {"id": "u1", "text": "你好啊", "start_time": 0, "end_time": 500, "words": []},
                {"id": "u2", "text": "这是一段", "start_time": 500, "end_time": 1100, "words": []},
                {"id": "u3", "text": "测试转写。", "start_time": 1100, "end_time": 1800, "words": []},
            ]
        },
    )
    assert save.status_code == 200
    assert "corrected_text" not in save.json()["task"]

    detail = client.get(f"/site/tasks/{submit['task']['id']}/editor")
    assert detail.status_code == 200
    assert [item["text"] for item in detail.json()["editor"]["utterances"]] == ["你好啊", "这是一段", "测试转写。"]
    repo.close()


def test_site_task_exports_corrected_srt_text_and_doc(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    workspace_id = repo.create_workspace("ASR 网站", "detailed_summary")
    store = ASRSiteStore(repo)
    try:
        user = store.create_user("Alice")
        task_id = store.next_id("task")
        store.create_pending_task(
            task_id=task_id,
            user_id=user["id"],
            workspace_id=workspace_id,
            title="客户回访.m4a",
            source_name="客户回访.m4a",
            content_type="audio/mp4",
            original_size_bytes=1024,
            duration_seconds=3.0,
            points_cost=1,
            charge_basis="3.0s -> 1 points",
            agreement_version="v1",
            local_file_path="/tmp/customer-call.m4a",
        )
        store.save_correction(
            task_id,
            utterances=[
                {"id": "u1", "text": "你好啊", "start_time": 0, "end_time": 500, "words": []},
                {"id": "u2", "text": "这是一段", "start_time": 500, "end_time": 1100, "words": []},
                {"id": "u3", "text": "测试转写。", "start_time": 1100, "end_time": 1800, "words": []},
            ],
        )
    finally:
        store.close()

    app = create_app(repo)
    client = TestClient(app)
    token = api_module.create_site_session_token(user["id"])

    srt = client.get(f"/site/tasks/{task_id}/export?format=srt")
    text = client.get(f"/site/tasks/{task_id}/export?format=text")
    doc = client.get(f"/site/me/tasks/{task_id}/export?format=doc&site_token={token}")

    assert srt.status_code == 200
    assert srt.headers["content-disposition"].endswith("%E5%AE%A2%E6%88%B7%E5%9B%9E%E8%AE%BF.srt")
    assert srt.text == (
        "1\n"
        "00:00:00,000 --> 00:00:00,500\n"
        "你好啊\n\n"
        "2\n"
        "00:00:00,500 --> 00:00:01,100\n"
        "这是一段\n\n"
        "3\n"
        "00:00:01,100 --> 00:00:01,800\n"
        "测试转写。\n"
    )
    assert text.status_code == 200
    assert text.headers["content-disposition"].endswith("%E5%AE%A2%E6%88%B7%E5%9B%9E%E8%AE%BF.txt")
    assert text.text == "你好啊\n这是一段\n测试转写。\n"
    assert doc.status_code == 200
    assert doc.headers["content-disposition"].endswith("%E5%AE%A2%E6%88%B7%E5%9B%9E%E8%AE%BF.doc")
    assert "<p>你好啊</p>" in doc.text
    repo.close()


def test_site_can_delete_task(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)

    monkeypatch.setattr(api_module, "probe_media_duration_seconds", lambda file_path: 61.0)

    user = client.post("/site/users", json={"name": "Alice"}).json()["user"]
    client.post(f"/site/users/{user['id']}/recharge", json={"points": 10})
    submit = client.post(
        f"/site/users/{user['id']}/tasks",
        files={"file": ("call.mp3", b"fake-mp3-data", "audio/mpeg")},
    ).json()

    remove = client.delete(f"/site/tasks/{submit['task']['id']}")
    tasks = client.get(f"/site/users/{user['id']}/tasks")

    assert remove.status_code == 200
    assert remove.json()["ok"] is True
    assert tasks.status_code == 200
    assert tasks.json()["tasks"] == []
    repo.close()


def test_site_can_rename_task(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)

    monkeypatch.setattr(api_module, "probe_media_duration_seconds", lambda file_path: 61.0)

    user = client.post("/site/users", json={"name": "Alice"}).json()["user"]
    client.post(f"/site/users/{user['id']}/recharge", json={"points": 10})
    submit = client.post(
        f"/site/users/{user['id']}/tasks",
        files={"file": ("call.mp3", b"fake-mp3-data", "audio/mpeg")},
    ).json()

    renamed = client.patch(
        f"/site/tasks/{submit['task']['id']}",
        json={"title": "新的任务名.m4a"},
    )
    detail = client.get(f"/site/tasks/{submit['task']['id']}")

    assert renamed.status_code == 200
    assert renamed.json()["task"]["title"] == "新的任务名.m4a"
    assert renamed.json()["task"]["source_name"] == "新的任务名.m4a"
    assert detail.status_code == 200
    assert detail.json()["task"]["title"] == "新的任务名.m4a"
    repo.close()


def test_site_user_task_list_is_lightweight_without_editor_payload(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)

    monkeypatch.setattr(api_module, "probe_media_duration_seconds", lambda file_path: 61.0)
    monkeypatch.setattr(worker_module, "compress_audio_for_asr", lambda data, filename, content_type: b"OGGDATA")
    monkeypatch.setattr(
        worker_module,
        "upload_media_to_b2",
        fake_b2_upload,
    )
    monkeypatch.setattr(worker_module, "build_authorized_download_url", lambda object_name: "https://download")
    monkeypatch.setattr(worker_module, "request_bytes", lambda request, timeout_seconds: b"OGGDATA")

    class FakeASRClient:
        config = type("Config", (), {"timeout_seconds": 30, "show_utterances": True})()

        def transcribe_url(self, url, content_type=None):
            return {
                "task_id": "stepaudio-task-1",
                "text": "你好，这是一段测试转写。",
                "utterances": [
                    {"text": "你好", "start_time": 0, "end_time": 500},
                    {"text": "这是一段测试转写。", "start_time": 500, "end_time": 1800},
                ],
                "raw_result": {
                    "result": [
                        {
                            "text": "你好，这是一段测试转写。",
                            "utterances": [
                                {"text": "你好", "start_time": 0, "end_time": 500},
                                {"text": "这是一段测试转写。", "start_time": 500, "end_time": 1800},
                            ],
                        }
                    ]
                },
            }

    monkeypatch.setattr(worker_module.StepFunASRClient, "from_env", classmethod(lambda cls: FakeASRClient()))

    user = client.post("/site/users", json={"name": "Alice"}).json()["user"]
    client.post(f"/site/users/{user['id']}/recharge", json={"points": 10})
    submit = client.post(
        f"/site/users/{user['id']}/tasks",
        files={"file": ("call.mp3", b"fake-mp3-data", "audio/mpeg")},
    ).json()
    client.post(f"/site/tasks/{submit['task']['id']}/start", json={"confirm_points": True})
    drain_site_task_jobs(repo)

    response = client.get(f"/site/users/{user['id']}/tasks")
    assert response.status_code == 200
    task = response.json()["tasks"][0]
    assert "utterances" not in task
    assert "raw_result" not in task
    assert "transcript_text" not in task
    assert "corrected_text" not in task
    assert "raw_asr_result" not in (task.get("media") or {})
    assert task["status"] == "completed"
    repo.close()


def test_site_task_detail_is_lightweight_and_editor_payload_moves_to_editor_endpoint(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)

    monkeypatch.setattr(api_module, "probe_media_duration_seconds", lambda file_path: 61.0)
    monkeypatch.setattr(worker_module, "compress_audio_for_asr", lambda data, filename, content_type: b"OGGDATA")
    monkeypatch.setattr(
        worker_module,
        "upload_media_to_b2",
        fake_b2_upload,
    )
    monkeypatch.setattr(worker_module, "build_authorized_download_url", lambda object_name: "https://download")
    monkeypatch.setattr(worker_module, "request_bytes", lambda request, timeout_seconds: b"OGGDATA")

    class FakeASRClient:
        config = type("Config", (), {"timeout_seconds": 30, "show_utterances": True})()

        def transcribe_url(self, url, content_type=None):
            return {
                "task_id": "stepaudio-task-1",
                "text": "你好，这是一段测试转写。",
                "utterances": [
                    {"text": "你好", "start_time": 0, "end_time": 500},
                    {"text": "这是一段测试转写。", "start_time": 500, "end_time": 1800},
                ],
                "raw_result": {
                    "result": [
                        {
                            "text": "你好，这是一段测试转写。",
                            "utterances": [
                                {"text": "你好", "start_time": 0, "end_time": 500},
                                {"text": "这是一段测试转写。", "start_time": 500, "end_time": 1800},
                            ],
                        }
                    ]
                },
            }

    monkeypatch.setattr(worker_module.StepFunASRClient, "from_env", classmethod(lambda cls: FakeASRClient()))

    user = client.post("/site/users", json={"name": "Alice"}).json()["user"]
    client.post(f"/site/users/{user['id']}/recharge", json={"points": 10})
    submit = client.post(
        f"/site/users/{user['id']}/tasks",
        files={"file": ("call.mp3", b"fake-mp3-data", "audio/mpeg")},
    ).json()
    client.post(f"/site/tasks/{submit['task']['id']}/start", json={"confirm_points": True})
    drain_site_task_jobs(repo)

    detail = client.get(f"/site/tasks/{submit['task']['id']}")
    assert detail.status_code == 200
    task = detail.json()["task"]
    assert "utterances" not in task
    assert "raw_result" not in task
    assert "transcript_text" not in task
    assert "corrected_text" not in task
    assert "raw_asr_result" not in (task.get("media") or {})

    editor = client.get(f"/site/tasks/{submit['task']['id']}/editor")
    assert editor.status_code == 200
    editor_payload = editor.json()
    editor_task = editor_payload["task"]
    assert editor_task["media"]["public_url"] == "https://public.example.com/audio.ogg"
    assert "raw_asr_result" not in editor_task["media"]
    assert "utterances" not in editor_task["media"]
    assert "transcript_text" not in editor_task["media"]
    assert editor_payload["editor"]["utterances"][0]["text"] == "你好"
    assert editor_payload["editor"]["utterances"][1]["text"] == "这是一段测试转写。"
    assert editor_task["media"]["public_url"] == "https://public.example.com/audio.ogg"
    repo.close()
