from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response


# Uvicorn configures this logger hierarchy at INFO in production, so the
# structured records are emitted without installing a competing root handler.
LOGGER = logging.getLogger("uvicorn.error.recordflow.http_guard")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass(frozen=True)
class RateLimitRule:
    name: str
    requests: int


class SlidingWindowRateLimiter:
    """Small, process-local limiter with bounded memory usage."""

    def __init__(
        self,
        *,
        enabled: bool,
        window_seconds: float,
        rules: dict[str, RateLimitRule],
        max_keys: int,
        cleanup_interval: int = 128,
    ) -> None:
        self.enabled = enabled
        self.window_seconds = max(1.0, float(window_seconds))
        self.rules = rules
        self.max_keys = max(1, int(max_keys))
        self.cleanup_interval = max(1, int(cleanup_interval))
        self._buckets: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()
        self._checks = 0
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> SlidingWindowRateLimiter:
        return cls(
            enabled=env_bool("RECORDFLOW_RATE_LIMIT_ENABLED", True),
            window_seconds=env_float("RECORDFLOW_RATE_LIMIT_WINDOW_SECONDS", 60.0),
            max_keys=env_int("RECORDFLOW_RATE_LIMIT_MAX_KEYS", 10000),
            rules={
                "auth": RateLimitRule(
                    "auth", env_int("RECORDFLOW_RATE_LIMIT_AUTH_REQUESTS", 20)
                ),
                "direct_upload_init": RateLimitRule(
                    "direct_upload_init",
                    env_int("RECORDFLOW_RATE_LIMIT_DIRECT_UPLOAD_INIT_REQUESTS", 30),
                ),
                "task_upload": RateLimitRule(
                    "task_upload", env_int("RECORDFLOW_RATE_LIMIT_TASK_UPLOAD_REQUESTS", 12)
                ),
                "wechatpay": RateLimitRule(
                    "wechatpay", env_int("RECORDFLOW_RATE_LIMIT_WECHATPAY_REQUESTS", 12)
                ),
                "export": RateLimitRule(
                    "export", env_int("RECORDFLOW_RATE_LIMIT_EXPORT_REQUESTS", 60)
                ),
            },
        )

    def retry_after(self, scope: str, client_id: str, now: float | None = None) -> int | None:
        if not self.enabled:
            return None
        rule = self.rules.get(scope)
        if rule is None or rule.requests <= 0:
            return None
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds
        key = (scope, client_id)
        with self._lock:
            self._checks += 1
            if self._checks % self.cleanup_interval == 0:
                self._cleanup(cutoff)
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self.max_keys:
                    self._buckets.popitem(last=False)
                bucket = deque()
                self._buckets[key] = bucket
            else:
                self._buckets.move_to_end(key)
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= rule.requests:
                return max(1, math.ceil(self.window_seconds - (current - bucket[0])))
            bucket.append(current)
            return None

    def _cleanup(self, cutoff: float) -> None:
        for key, bucket in list(self._buckets.items()):
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if not bucket:
                self._buckets.pop(key, None)


class RequestGuard:
    def __init__(self, limiter: SlidingWindowRateLimiter, *, trust_proxy_headers: bool = False) -> None:
        self.limiter = limiter
        self.trust_proxy_headers = trust_proxy_headers

    @classmethod
    def from_env(cls) -> RequestGuard:
        return cls(
            SlidingWindowRateLimiter.from_env(),
            trust_proxy_headers=env_bool("RECORDFLOW_TRUST_PROXY_HEADERS", False),
        )

    async def handle(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request_id_for(request)
        request.state.request_id = request_id
        started = time.perf_counter()
        scope = sensitive_rate_limit_scope(request.url.path, request.method)
        retry_after = None
        if scope:
            retry_after = self.limiter.retry_after(scope, self._client_id(request))

        if retry_after is not None:
            response = JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."},
                headers={"Retry-After": str(retry_after)},
            )
        else:
            try:
                response = await call_next(request)
            except Exception as exc:  # pragma: no cover - exercised via integration behavior
                log_json(
                    logging.ERROR,
                    event="http_request_exception",
                    request_id=request_id,
                    method=request.method,
                    path=request.url.path,
                    exception_type=type(exc).__name__,
                )
                response = JSONResponse(
                    status_code=500,
                    content={"detail": "Internal server error.", "request_id": request_id},
                )

        response.headers["X-Request-ID"] = request_id
        log_json(
            logging.INFO,
            event="http_request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return response

    def _client_id(self, request: Request) -> str:
        if self.trust_proxy_headers:
            forwarded_for = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
            if forwarded_for:
                return forwarded_for[:128]
        if request.client and request.client.host:
            return request.client.host[:128]
        return "unknown"


def request_id_for(request: Request) -> str:
    provided = request.headers.get("X-Request-ID", "").strip()
    if REQUEST_ID_PATTERN.fullmatch(provided):
        return provided
    return uuid.uuid4().hex


def sensitive_rate_limit_scope(path: str, method: str = "") -> str | None:
    if path.startswith("/site/auth/"):
        return "auth"
    if path == "/site/me/tasks/direct-upload/init":
        return "direct_upload_init"
    if path == "/site/me/tasks" and method.upper() == "POST":
        return "task_upload"
    if "/wechatpay" in path:
        return "wechatpay"
    if path.endswith("/export"):
        return "export"
    return None


def log_deprecated_query_token(request: Request) -> None:
    log_json(
        logging.WARNING,
        event="deprecated_site_token_query",
        request_id=getattr(request.state, "request_id", "unknown"),
        method=request.method,
        path=request.url.path,
    )


def log_json(level: int, *, event: str, **fields: object) -> None:
    LOGGER.log(
        level,
        json.dumps({"event": event, **fields}, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
    )


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or str(default))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)) or str(default))
    except ValueError:
        return default
