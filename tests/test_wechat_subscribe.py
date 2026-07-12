import json

from recordflow_agent import wechat_subscribe as subscribe_module
from recordflow_agent.wechat_subscribe import (
    send_task_complete_subscription,
    task_complete_subscription_config,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_task_complete_subscription_is_disabled_without_template(monkeypatch):
    monkeypatch.delenv("WECHAT_SUBSCRIBE_TASK_COMPLETE_TEMPLATE_ID", raising=False)

    assert task_complete_subscription_config() == {
        "enabled": False,
        "template_id": "",
    }
    assert send_task_complete_subscription(
        openid="openid-1",
        task={"id": "task-1", "title": "meeting.mp3"},
    ) is False


def test_subscription_config_requires_complete_wechat_credentials(monkeypatch):
    monkeypatch.setenv("WECHAT_SUBSCRIBE_TASK_COMPLETE_TEMPLATE_ID", "template-1")
    monkeypatch.delenv("WECHAT_MINIAPP_APPID", raising=False)
    monkeypatch.delenv("WECHAT_MINIAPP_SECRET", raising=False)

    assert task_complete_subscription_config() == {
        "enabled": False,
        "template_id": "template-1",
    }


def test_task_complete_subscription_uses_configured_fields_and_cached_token(monkeypatch):
    monkeypatch.setenv("WECHAT_MINIAPP_APPID", "wx-test")
    monkeypatch.setenv("WECHAT_MINIAPP_SECRET", "secret")
    monkeypatch.setenv("WECHAT_SUBSCRIBE_TASK_COMPLETE_TEMPLATE_ID", "template-1")
    monkeypatch.setenv("WECHAT_SUBSCRIBE_TASK_COMPLETE_TITLE_FIELD", "thing4")
    monkeypatch.setenv("WECHAT_SUBSCRIBE_TASK_COMPLETE_STATUS_FIELD", "phrase5")
    monkeypatch.setenv("WECHAT_SUBSCRIBE_TASK_COMPLETE_TIME_FIELD", "time6")
    monkeypatch.setenv("WECHAT_SUBSCRIBE_TASK_COMPLETE_PAGE", "pages/task/task?id={task_id}")
    monkeypatch.setenv("WECHAT_SUBSCRIBE_MINIPROGRAM_STATE", "trial")
    subscribe_module._TOKEN_CACHE.clear()
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.method == "GET":
            return FakeResponse({"access_token": "access-token", "expires_in": 7200})
        return FakeResponse({"errcode": 0, "errmsg": "ok"})

    monkeypatch.setattr(subscribe_module, "urlopen", fake_urlopen)
    task = {
        "id": "task_123",
        "title": "一场需要截断到微信字段上限的产品需求评审会议录音.mp3",
        "completed_at": "2026-07-11T01:30:00+00:00",
        "updated_at": "2026-07-11T02:45:00+00:00",
        "notification_template_id": "template-granted",
    }

    assert send_task_complete_subscription(openid="openid-1", task=task) is True
    assert send_task_complete_subscription(openid="openid-1", task=task) is True

    assert [request.method for request in requests] == ["GET", "POST", "POST"]
    payload = json.loads(requests[1].data.decode("utf-8"))
    assert payload["touser"] == "openid-1"
    assert payload["template_id"] == "template-granted"
    assert payload["page"] == "pages/task/task?id=task_123"
    assert payload["miniprogram_state"] == "trial"
    assert payload["data"]["phrase5"]["value"] == "转写完成"
    assert len(payload["data"]["thing4"]["value"]) == 20
    assert payload["data"]["time6"]["value"] == "2026-07-11 09:30"


def test_task_complete_subscription_refreshes_an_invalid_access_token(monkeypatch):
    monkeypatch.setenv("WECHAT_MINIAPP_APPID", "wx-refresh")
    monkeypatch.setenv("WECHAT_MINIAPP_SECRET", "secret")
    monkeypatch.setenv("WECHAT_SUBSCRIBE_TASK_COMPLETE_TEMPLATE_ID", "template-1")
    subscribe_module._TOKEN_CACHE.clear()
    token_responses = iter(["expired-token", "fresh-token"])
    sent_tokens = []

    def fake_urlopen(request, timeout):
        if request.method == "GET":
            return FakeResponse(
                {"access_token": next(token_responses), "expires_in": 7200}
            )
        token = request.full_url.rsplit("=", 1)[-1]
        sent_tokens.append(token)
        if token == "expired-token":
            return FakeResponse({"errcode": 42001, "errmsg": "access_token expired"})
        return FakeResponse({"errcode": 0, "errmsg": "ok"})

    monkeypatch.setattr(subscribe_module, "urlopen", fake_urlopen)

    assert send_task_complete_subscription(
        openid="openid-1",
        task={"id": "task-1", "title": "meeting.mp3"},
    ) is True
    assert sent_tokens == ["expired-token", "fresh-token"]
