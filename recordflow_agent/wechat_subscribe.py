from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


WECHAT_ACCESS_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
WECHAT_SUBSCRIBE_SEND_URL = "https://api.weixin.qq.com/cgi-bin/message/subscribe/send"
INVALID_ACCESS_TOKEN_CODES = frozenset({40001, 40014, 42001})
CHINA_TIMEZONE = ZoneInfo("Asia/Shanghai")


class WechatSubscribeError(RuntimeError):
    pass


@dataclass(frozen=True)
class TaskCompleteSubscribeSettings:
    appid: str
    secret: str
    template_id: str
    title_field: str = "thing3"
    status_field: str = "thing2"
    completed_at_field: str = "time1"
    status_value: str = "转写完成"
    page: str = "pages/task/task?id={task_id}"
    miniprogram_state: str = ""
    lang: str = "zh_CN"
    timeout_seconds: float = 5.0

    @classmethod
    def from_env(
        cls,
        template_id: str | None = None,
    ) -> TaskCompleteSubscribeSettings | None:
        template_id = (
            template_id
            if template_id is not None
            else os.getenv("WECHAT_SUBSCRIBE_TASK_COMPLETE_TEMPLATE_ID", "")
        ).strip()
        if not template_id:
            return None
        appid = os.getenv("WECHAT_MINIAPP_APPID", "").strip()
        secret = os.getenv("WECHAT_MINIAPP_SECRET", "").strip()
        if not appid or not secret:
            raise WechatSubscribeError(
                "WECHAT_MINIAPP_APPID and WECHAT_MINIAPP_SECRET are required for subscriptions."
            )
        miniprogram_state = os.getenv("WECHAT_SUBSCRIBE_MINIPROGRAM_STATE", "").strip()
        if miniprogram_state and miniprogram_state not in {"developer", "trial", "formal"}:
            raise WechatSubscribeError(
                "WECHAT_SUBSCRIBE_MINIPROGRAM_STATE must be developer, trial, or formal."
            )
        try:
            timeout_seconds = max(
                1.0,
                float(os.getenv("WECHAT_SUBSCRIBE_TIMEOUT_SECONDS", "5") or "5"),
            )
        except ValueError as exc:
            raise WechatSubscribeError(
                "WECHAT_SUBSCRIBE_TIMEOUT_SECONDS must be numeric."
            ) from exc
        return cls(
            appid=appid,
            secret=secret,
            template_id=template_id,
            title_field=os.getenv(
                "WECHAT_SUBSCRIBE_TASK_COMPLETE_TITLE_FIELD", "thing3"
            ).strip(),
            status_field=os.getenv(
                "WECHAT_SUBSCRIBE_TASK_COMPLETE_STATUS_FIELD", "thing2"
            ).strip(),
            completed_at_field=os.getenv(
                "WECHAT_SUBSCRIBE_TASK_COMPLETE_TIME_FIELD", "time1"
            ).strip(),
            status_value=os.getenv(
                "WECHAT_SUBSCRIBE_TASK_COMPLETE_STATUS_VALUE", "转写完成"
            ).strip()
            or "转写完成",
            page=os.getenv(
                "WECHAT_SUBSCRIBE_TASK_COMPLETE_PAGE",
                "pages/task/task?id={task_id}",
            ).strip(),
            miniprogram_state=miniprogram_state,
            lang=os.getenv("WECHAT_SUBSCRIBE_LANG", "zh_CN").strip() or "zh_CN",
            timeout_seconds=timeout_seconds,
        )


_TOKEN_CACHE: dict[tuple[str, str], tuple[str, float]] = {}
_TOKEN_LOCK = threading.Lock()


def task_complete_subscription_config() -> dict[str, Any]:
    template_id = os.getenv("WECHAT_SUBSCRIBE_TASK_COMPLETE_TEMPLATE_ID", "").strip()
    appid = os.getenv("WECHAT_MINIAPP_APPID", "").strip()
    secret = os.getenv("WECHAT_MINIAPP_SECRET", "").strip()
    return {
        "enabled": bool(template_id and appid and secret),
        "template_id": template_id,
    }


def send_task_complete_subscription(*, openid: str, task: dict[str, Any]) -> bool:
    """Send one completion subscription, or return False when the feature is disabled."""
    stored_template_id = str(task.get("notification_template_id") or "").strip()
    settings = TaskCompleteSubscribeSettings.from_env(stored_template_id or None)
    if settings is None:
        return False
    openid = openid.strip()
    if not openid:
        raise WechatSubscribeError("A WeChat openid is required for subscriptions.")

    token = _get_access_token(settings)
    response = _send_message(settings, token, openid, task)
    errcode = _errcode(response)
    if errcode in INVALID_ACCESS_TOKEN_CODES:
        _clear_cached_token(settings)
        token = _get_access_token(settings, force_refresh=True)
        response = _send_message(settings, token, openid, task)
        errcode = _errcode(response)
    if errcode != 0:
        raise WechatSubscribeError(
            f"WeChat subscription send failed ({errcode}): {response.get('errmsg', 'unknown error')}"
        )
    return True


def build_task_complete_message(
    settings: TaskCompleteSubscribeSettings,
    *,
    openid: str,
    task: dict[str, Any],
) -> dict[str, Any]:
    task_id = quote(str(task.get("id") or ""), safe="")
    try:
        page = settings.page.format(task_id=task_id)
    except (KeyError, ValueError) as exc:
        raise WechatSubscribeError(
            "WECHAT_SUBSCRIBE_TASK_COMPLETE_PAGE may only use the {task_id} placeholder."
        ) from exc

    data: dict[str, dict[str, str]] = {}
    if settings.title_field:
        data[settings.title_field] = {
            "value": _compact_text(task.get("title") or task.get("source_name"), 20)
            or "音频转写任务"
        }
    if settings.status_field:
        data[settings.status_field] = {
            "value": _compact_text(settings.status_value, 5) or "转写完成"
        }
    if settings.completed_at_field:
        data[settings.completed_at_field] = {
            "value": _format_completed_at(task.get("completed_at") or task.get("updated_at"))
        }

    message: dict[str, Any] = {
        "touser": openid,
        "template_id": settings.template_id,
        "page": page,
        "lang": settings.lang,
        "data": data,
    }
    if settings.miniprogram_state:
        message["miniprogram_state"] = settings.miniprogram_state
    return message


def _get_access_token(
    settings: TaskCompleteSubscribeSettings,
    *,
    force_refresh: bool = False,
) -> str:
    cache_key = (settings.appid, settings.secret)
    with _TOKEN_LOCK:
        now = time.monotonic()
        cached = _TOKEN_CACHE.get(cache_key)
        if not force_refresh and cached and cached[1] > now:
            return cached[0]

        query = urlencode(
            {
                "grant_type": "client_credential",
                "appid": settings.appid,
                "secret": settings.secret,
            }
        )
        response = _request_json(
            Request(f"{WECHAT_ACCESS_TOKEN_URL}?{query}", method="GET"),
            timeout_seconds=settings.timeout_seconds,
            operation="access token request",
        )
        errcode = _errcode(response)
        token = str(response.get("access_token") or "").strip()
        if errcode != 0 or not token:
            raise WechatSubscribeError(
                f"WeChat access token request failed ({errcode}): "
                f"{response.get('errmsg', 'missing access_token')}"
            )
        try:
            expires_in = max(60, int(response.get("expires_in") or 7200))
        except (TypeError, ValueError):
            expires_in = 7200
        refresh_margin = min(300, max(30, expires_in // 10))
        _TOKEN_CACHE[cache_key] = (token, now + expires_in - refresh_margin)
        return token


def _send_message(
    settings: TaskCompleteSubscribeSettings,
    access_token: str,
    openid: str,
    task: dict[str, Any],
) -> dict[str, Any]:
    payload = build_task_complete_message(settings, openid=openid, task=task)
    request = Request(
        f"{WECHAT_SUBSCRIBE_SEND_URL}?{urlencode({'access_token': access_token})}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    return _request_json(
        request,
        timeout_seconds=settings.timeout_seconds,
        operation="subscription send",
    )


def _request_json(
    request: Request,
    *,
    timeout_seconds: float,
    operation: str,
) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except HTTPError as exc:
        raise WechatSubscribeError(
            f"WeChat {operation} returned HTTP {exc.code}."
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise WechatSubscribeError(f"WeChat {operation} failed.") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WechatSubscribeError(
            f"WeChat {operation} returned invalid JSON."
        ) from exc
    if not isinstance(payload, dict):
        raise WechatSubscribeError(f"WeChat {operation} returned an invalid payload.")
    return payload


def _clear_cached_token(settings: TaskCompleteSubscribeSettings) -> None:
    with _TOKEN_LOCK:
        _TOKEN_CACHE.pop((settings.appid, settings.secret), None)


def _errcode(payload: dict[str, Any]) -> int:
    try:
        return int(payload.get("errcode") or 0)
    except (TypeError, ValueError):
        return -1


def _compact_text(value: Any, max_length: int) -> str:
    return " ".join(str(value or "").split())[:max_length]


def _format_completed_at(value: Any) -> str:
    completed_at: datetime
    if isinstance(value, datetime):
        completed_at = value
    elif value:
        try:
            completed_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            completed_at = datetime.now(CHINA_TIMEZONE)
    else:
        completed_at = datetime.now(CHINA_TIMEZONE)
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=timezone.utc)
    return completed_at.astimezone(CHINA_TIMEZONE).strftime("%Y-%m-%d %H:%M")
