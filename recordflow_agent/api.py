from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import re
import secrets
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.parse import urlencode
from urllib.parse import quote as url_quote
from urllib.parse import urlparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from recordflow_agent.asr_site import (
    AGREEMENT_VERSION,
    ASRSiteStore,
    SITE_WORKSPACE_NAME,
    SITE_WORKSPACE_PROFILE,
    build_srt_export,
    build_text_export,
    estimate_task_charge,
    pending_upload_path,
    pending_upload_root,
    remove_local_file_if_exists,
)
from recordflow_agent.cli import build_digest_renderer, build_extractor
from recordflow_agent.digest_engine import apply_digest_patch_json
from recordflow_agent.eval_loader import load_eval_dataset
from recordflow_agent.http_guard import RequestGuard, log_deprecated_query_token
from recordflow_agent.llm_client import load_dotenv
from recordflow_agent.media_storage import (
    B2ConfigurationError,
    B2UploadError,
    delete_media_from_b2,
    is_supported_upload_media,
    upload_media_to_b2,
)
from recordflow_agent.mobile_upload import MOBILE_UPLOAD_HTML
from recordflow_agent.pipeline import process_record
from recordflow_agent.profiles import load_profile
from recordflow_agent.repository_factory import create_repository
from recordflow_agent.serialization import to_jsonable
from recordflow_agent.web_ui import ADMIN_SITE_HTML, AGREEMENT_HTML
from recordflow_agent.wechat_subscribe import task_complete_subscription_config

SITE_TASK_MAX_AUDIO_BYTES = 200 * 1024 * 1024
SITE_TASK_AUDIO_MIME_TYPES = {
    "audio/aac",
    "audio/aiff",
    "audio/flac",
    "audio/l16",
    "audio/mp4",
    "audio/mpeg",
    "audio/mp3",
    "audio/ogg",
    "audio/opus",
    "audio/pcm",
    "audio/wav",
    "audio/wave",
    "audio/webm",
    "audio/x-aiff",
    "audio/x-m4a",
    "audio/x-wav",
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "video/x-m4v",
}
SITE_TASK_AUDIO_EXTENSIONS = {
    ".aac",
    ".aif",
    ".aiff",
    ".flac",
    ".m4a",
    ".m4v",
    ".mov",
    ".mp3",
    ".mp4",
    ".oga",
    ".ogg",
    ".opus",
    ".pcm",
    ".wav",
    ".webm",
}
WECHATPAY_UNAVAILABLE_DETAIL = "微信支付暂不可用，请稍后再试。"
SITE_TASK_ACTIVE_DELETE_STATUSES = frozenset({"starting", "queued", "transcribing"})
LOGGER = logging.getLogger(__name__)


class CreateWorkspaceRequest(BaseModel):
    name: str
    profile: str = "detailed_summary"


class CreateRecordRequest(BaseModel):
    title: str
    text: str
    use_llm: bool = False
    async_mode: bool = False


class ReviewUpdateRequest(BaseModel):
    status: str


class StateObjectPatchRequest(BaseModel):
    summary: str | None = None
    status: str | None = None
    payload: dict | None = None
    record_id: str = "user_patch"


class StateObjectClarifyRequest(BaseModel):
    note: str


class DigestPatchRequest(BaseModel):
    digest: dict
    patch: dict


class PersistedDigestPatchRequest(BaseModel):
    patch: dict


class LoadEvalRequest(BaseModel):
    reset: bool = True
    workspace_name: str = "data/eval 在线导入"
    profile: str = "detailed_summary"
    use_llm: bool = True


class CreateUserRequest(BaseModel):
    name: str


class WechatMiniappLoginRequest(BaseModel):
    code: str
    nickname: str | None = None
    agreement_version: str = ""
    agreement_accepted: bool = False


class DevSiteLoginRequest(BaseModel):
    nickname: str = "开发用户"
    agreement_version: str = ""
    agreement_accepted: bool = False


class AcceptSiteAgreementRequest(BaseModel):
    agreement_version: str
    agreement_accepted: bool = True


class UpdateSiteProfileRequest(BaseModel):
    name: str


class RechargePointsRequest(BaseModel):
    points: int
    note: str = ""


class AdminCreateUserRequest(BaseModel):
    name: str
    role: str = "user"
    initial_points: int = 0


class AdminUpdateUserRequest(BaseModel):
    name: str | None = None
    role: str | None = None


class AdminAdjustPointsRequest(BaseModel):
    delta: int
    note: str = ""


class CreateWechatPayRechargeRequest(BaseModel):
    points: int


class ConfirmWechatPayRechargeRequest(BaseModel):
    out_trade_no: str


class SaveCorrectionRequest(BaseModel):
    utterances: list[dict]


class StartTaskRequest(BaseModel):
    confirm_points: bool = True
    notify_on_complete: bool = False
    notification_template_id: str = ""


class RenameTaskRequest(BaseModel):
    title: str


class DirectUploadInitRequest(BaseModel):
    source_name: str = "recording.mp3"
    content_type: str | None = None
    size_bytes: int | None = None


class DirectUploadCompleteRequest(BaseModel):
    upload_token: str
    object_key: str | None = None


@dataclass(frozen=True)
class COSDirectUploadSettings:
    secret_id: str
    secret_key: str
    bucket: str
    region: str
    upload_url: str
    key_prefix: str
    public_base_url: str
    public_write: bool = False


class COSDirectUploadConfigurationError(RuntimeError):
    pass


def create_app(repo: object | None = None) -> FastAPI:
    load_dotenv()
    validate_site_session_configuration()
    app = FastAPI(title="RecordFlow Agent API", version="0.1.0")
    app.state.repo = repo or create_repository()
    app.state.frontend_dist = default_frontend_dist()
    app.state.request_guard = RequestGuard.from_env()

    @app.middleware("http")
    async def api_key_auth(request: Request, call_next):
        configured_key = os.getenv("RECORDFLOW_APP_API_KEY")
        public_path_prefixes = ("/assets/",)
        site_session_prefixes = ("/site/auth/", "/site/me")
        public_admin_shell = request.method == "GET" and (
            request.url.path == "/admin" or request.url.path.startswith("/admin/")
        )
        if (
            configured_key
            and request.url.path not in {"/", "/health", "/agreement", "/site/agreement"}
            and not request.url.path.startswith(public_path_prefixes)
            and not request.url.path.startswith(site_session_prefixes)
            and not public_admin_shell
        ):
            provided_key = request.headers.get("X-API-Key")
            if provided_key != configured_key:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or missing X-API-Key."},
                )
        return await call_next(request)

    @app.middleware("http")
    async def request_guard(request: Request, call_next):
        return await app.state.request_guard.handle(request, call_next)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/dashboard")
    def dashboard() -> dict:
        return build_dashboard(app.state.repo)

    @app.get("/assets/{asset_path:path}")
    def frontend_asset(asset_path: str):
        asset_file = app.state.frontend_dist / "assets" / asset_path
        if asset_file.exists() and asset_file.is_file():
            return FileResponse(asset_file)
        raise HTTPException(status_code=404, detail="Frontend asset not found.")

    @app.get("/admin", response_class=HTMLResponse)
    def admin_page():
        frontend_index = app.state.frontend_dist / "index.html"
        if frontend_index.exists():
            return FileResponse(frontend_index)
        return ADMIN_SITE_HTML

    @app.get("/admin/{admin_path:path}", response_class=HTMLResponse)
    def admin_spa_fallback(admin_path: str):
        frontend_index = app.state.frontend_dist / "index.html"
        if frontend_index.exists():
            return FileResponse(frontend_index)
        return ADMIN_SITE_HTML

    @app.get("/agreement", response_class=HTMLResponse)
    def agreement_page() -> str:
        return AGREEMENT_HTML

    @app.get("/mobile-upload", response_class=HTMLResponse)
    def mobile_upload_page() -> str:
        return MOBILE_UPLOAD_HTML

    @app.get("/site/agreement")
    def site_agreement_metadata() -> dict:
        return {
            "agreement": {
                "version": AGREEMENT_VERSION,
                "title": "RecordFlow 用户协议与隐私说明",
                "updated_at": "2026-07-11",
                "url": "/agreement",
            }
        }

    @app.post("/workspaces")
    def create_workspace(request: CreateWorkspaceRequest) -> dict[str, str]:
        try:
            profile = load_profile(request.profile)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        workspace_id = app.state.repo.create_workspace(request.name, profile.name)
        return {"id": workspace_id, "name": request.name, "profile": profile.name}

    @app.post("/workspaces/{workspace_id}/records")
    def create_record(workspace_id: str, request: CreateRecordRequest) -> dict:
        workspace = get_workspace_or_404(app.state.repo, workspace_id)
        if request.async_mode:
            job_id = app.state.repo.enqueue_record_job(
                workspace_id=workspace_id,
                title=request.title,
                text=request.text,
                use_llm=request.use_llm,
            )
            return {"job": app.state.repo.get_job(job_id)}
        profile = load_profile(workspace.profile)
        extractor = build_extractor(request.use_llm)
        digest = process_record(
            repo=app.state.repo,
            workspace_id=workspace_id,
            profile=profile,
            title=request.title,
            text=request.text,
            extractor=extractor,
            digest_renderer=build_digest_renderer(request.use_llm),
        )
        return {"digest": to_jsonable(digest)}

    @app.post("/digest/patch")
    def patch_digest(request: DigestPatchRequest) -> dict:
        try:
            digest = apply_digest_patch_json(request.digest, request.patch)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"digest": digest}

    @app.get("/records/{record_id}/digest")
    def get_record_digest(record_id: str) -> dict:
        try:
            return {"digest": app.state.repo.get_record_digest(record_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Digest not found.") from exc

    @app.post("/records/{record_id}/digest/patch")
    def patch_persisted_digest(record_id: str, request: PersistedDigestPatchRequest) -> dict:
        try:
            current_digest = app.state.repo.get_record_digest(record_id)
            patched_digest = apply_digest_patch_json(current_digest, request.patch)
            app.state.repo.save_record_digest(patched_digest)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"digest": patched_digest}

    @app.post("/media/uploads")
    async def upload_media(
        file: UploadFile = File(...),
        source_name: str = Form(""),
        compressed: bool = Form(False),
        original_size_bytes: int | None = Form(None),
        compressed_size_bytes: int | None = Form(None),
        compression_codec: str | None = Form(None),
        duration_seconds: float | None = Form(None),
    ) -> dict:
        media = await upload_media_file(
            file=file,
            source_name=source_name,
            compressed=compressed,
            original_size_bytes=original_size_bytes,
            compressed_size_bytes=compressed_size_bytes,
            compression_codec=compression_codec,
            duration_seconds=duration_seconds,
        )
        return {"media": media}

    @app.post("/workspaces/{workspace_id}/media/uploads")
    async def upload_workspace_media(
        workspace_id: str,
        file: UploadFile = File(...),
        source_name: str = Form(""),
        compressed: bool = Form(False),
        original_size_bytes: int | None = Form(None),
        compressed_size_bytes: int | None = Form(None),
        compression_codec: str | None = Form(None),
        duration_seconds: float | None = Form(None),
        title: str = Form(""),
        use_llm: bool = Form(False),
    ) -> dict:
        get_workspace_or_404(app.state.repo, workspace_id)
        media = await upload_media_file(
            file=file,
            source_name=source_name,
            compressed=compressed,
            original_size_bytes=original_size_bytes,
            compressed_size_bytes=compressed_size_bytes,
            compression_codec=compression_codec,
            duration_seconds=duration_seconds,
        )
        media_id = app.state.repo.add_media_record(
            workspace_id=workspace_id,
            source_name=media["source_name"],
            stored_name=media["stored_name"],
            url=media["url"],
            public_url=media["public_url"],
            object_name=media["object_name"],
            content_type=media["content_type"],
            original_size_bytes=media["original_size_bytes"],
            compressed_size_bytes=media["compressed_size_bytes"],
            compression_codec=media["compression_codec"],
        )
        saved_media = app.state.repo.get_media_record(media_id)
        job_id = app.state.repo.enqueue_media_compression_job(
            workspace_id=workspace_id,
            media_id=media_id,
            title=title.strip() or media["source_name"],
            use_llm=use_llm,
        )
        return {"media": saved_media, "job": app.state.repo.get_job(job_id)}

    @app.get("/workspaces/{workspace_id}/media")
    def list_workspace_media(workspace_id: str) -> dict:
        get_workspace_or_404(app.state.repo, workspace_id)
        return {"media": app.state.repo.list_media_records(workspace_id)}

    @app.get("/workspaces")
    def list_workspaces() -> dict:
        return {"workspaces": to_jsonable(app.state.repo.list_workspaces())}

    @app.get("/workspaces/{workspace_id}/records")
    def list_workspace_records(workspace_id: str) -> dict:
        get_workspace_or_404(app.state.repo, workspace_id)
        records = app.state.repo.list_records(workspace_id)
        return {
            "records": [
                {
                    **to_jsonable(record),
                    "digest": get_record_digest_or_none(app.state.repo, record.id),
                }
                for record in records
            ]
        }

    @app.post("/admin/load-eval")
    def load_eval(request: LoadEvalRequest) -> dict:
        eval_root = Path(__file__).resolve().parent.parent / "data" / "eval"
        return load_eval_dataset(
            app.state.repo,
            eval_root,
            workspace_name=request.workspace_name,
            profile_name=request.profile,
            use_llm=request.use_llm,
            reset=request.reset,
        )

    @app.get("/site/users")
    def list_site_users() -> dict:
        store = open_site_store(app.state.repo)
        try:
            return {"users": store.list_users()}
        finally:
            store.close()

    @app.post("/site/users")
    def create_site_user(request: CreateUserRequest) -> dict:
        if not request.name.strip():
            raise HTTPException(status_code=400, detail="User name is required.")
        store = open_site_store(app.state.repo)
        try:
            return {"user": store.create_user(request.name.strip())}
        finally:
            store.close()

    @app.post("/site/auth/dev/login")
    def login_site_dev(request: DevSiteLoginRequest) -> dict:
        if os.getenv("RECORDFLOW_ENABLE_DEV_LOGIN", "1").lower() in {"0", "false", "no"}:
            raise HTTPException(status_code=404, detail="Dev login is disabled.")
        agreement_version = validate_agreement_acceptance(
            request.agreement_accepted,
            request.agreement_version,
        )
        name = request.nickname.strip() or "开发用户"
        signup_points = max(0, int(os.getenv("RECORDFLOW_MINIAPP_SIGNUP_POINTS", "100") or "100"))
        store = open_site_store(app.state.repo)
        try:
            users = store.list_users()
            user = next((item for item in users if item["name"] == name), None)
            if user is None:
                user = store.create_user(name)
                if signup_points > 0:
                    user = store.add_points(
                        user["id"],
                        delta=signup_points,
                        kind="dev_signup_bonus",
                        note="miniapp dev login bonus",
                    )
            agreement = (
                store.accept_user_agreement(
                    user["id"],
                    agreement_version=agreement_version,
                    client="wechat-miniapp-dev",
                )
                if agreement_version
                else None
            )
            token = create_site_session_token(user["id"])
            return {
                "token": token,
                "token_type": "Bearer",
                "expires_in": site_session_ttl_seconds(),
                "user": user,
                "agreement": agreement,
            }
        finally:
            store.close()

    @app.post("/site/auth/wechat/login")
    def login_site_wechat(request: WechatMiniappLoginRequest) -> dict:
        agreement_version = validate_agreement_acceptance(
            request.agreement_accepted,
            request.agreement_version,
        )
        code = request.code.strip()
        if not code:
            raise HTTPException(status_code=400, detail="code is required.")
        appid = os.getenv("WECHAT_MINIAPP_APPID", "").strip()
        secret = os.getenv("WECHAT_MINIAPP_SECRET", "").strip()
        if not appid or not secret:
            raise HTTPException(
                status_code=503,
                detail="WECHAT_MINIAPP_APPID and WECHAT_MINIAPP_SECRET are required.",
            )
        session = exchange_wechat_code_for_session(appid=appid, secret=secret, code=code)
        openid = str(session.get("openid") or "").strip()
        session_key = str(session.get("session_key") or "").strip()
        if not openid or not session_key:
            raise HTTPException(status_code=502, detail="WeChat did not return openid/session_key.")
        unionid = str(session.get("unionid") or "").strip() or None
        signup_points = max(0, int(os.getenv("RECORDFLOW_MINIAPP_SIGNUP_POINTS", "100") or "100"))
        store = open_site_store(app.state.repo)
        try:
            user = store.get_or_create_wechat_user(
                appid=appid,
                openid=openid,
                unionid=unionid,
                session_key=session_key,
                default_name=(request.nickname or "").strip() or "微信用户",
                signup_points=signup_points,
            )
            agreement = (
                store.accept_user_agreement(
                    user["id"],
                    agreement_version=agreement_version,
                    client="wechat-miniapp",
                )
                if agreement_version
                else None
            )
            token = create_site_session_token(user["id"])
            return {
                "token": token,
                "token_type": "Bearer",
                "expires_in": site_session_ttl_seconds(),
                "user": user,
                "agreement": agreement,
            }
        finally:
            store.close()

    @app.get("/site/me")
    def get_site_me(request: Request) -> dict:
        store = open_site_store(app.state.repo)
        try:
            user = require_site_session_user(request, store)
            return {
                "user": user,
                "agreement": {
                    "version": AGREEMENT_VERSION,
                    "accepted": store.has_accepted_user_agreement(user["id"], AGREEMENT_VERSION),
                },
            }
        finally:
            store.close()

    @app.get("/site/me/point-ledger")
    def list_site_me_point_ledger(request: Request, limit: int = 20, cursor: str = "") -> dict:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 100.")
        cursor_created_at, cursor_id = decode_point_ledger_cursor(cursor)
        store = open_site_store(app.state.repo)
        try:
            user = require_site_session_user(request, store)
            entries, has_more = store.list_point_ledger_page(
                user["id"],
                limit=limit,
                cursor_created_at=cursor_created_at,
                cursor_id=cursor_id,
            )
            public_entries = [public_point_ledger_entry(entry) for entry in entries]
            next_cursor = encode_point_ledger_cursor(entries[-1]) if has_more and entries else ""
            return {
                "user": user,
                "entries": public_entries,
                "has_more": has_more,
                "next_cursor": next_cursor,
            }
        finally:
            store.close()

    @app.post("/site/me/agreement")
    def accept_site_me_agreement(request: Request, body: AcceptSiteAgreementRequest) -> dict:
        agreement_version = validate_agreement_acceptance(
            body.agreement_accepted,
            body.agreement_version,
        )
        store = open_site_store(app.state.repo)
        try:
            user = require_site_session_user(request, store)
            agreement = store.accept_user_agreement(
                user["id"],
                agreement_version=agreement_version,
                client="wechat-miniapp",
            )
            return {"agreement": agreement}
        finally:
            store.close()

    @app.patch("/site/me/profile")
    def update_site_me_profile(request: Request, body: UpdateSiteProfileRequest) -> dict:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required.")
        store = open_site_store(app.state.repo)
        try:
            user = require_site_session_user(request, store)
            return {"user": store.update_user_name(user["id"], name)}
        finally:
            store.close()

    @app.post("/site/me/recharge/wechatpay")
    def create_site_me_wechatpay_recharge(request: Request, body: CreateWechatPayRechargeRequest) -> dict:
        package = recharge_package_or_400(body.points)
        store = open_site_store(app.state.repo)
        try:
            user = require_site_session_user(request, store)
            openid = store.get_user_wechat_openid(user["id"], os.getenv("WECHAT_MINIAPP_APPID", "").strip())
            if not openid:
                raise HTTPException(status_code=400, detail="当前账号没有绑定微信 openid，无法发起微信支付。")
        finally:
            store.close()
        payment = create_wechatpay_jsapi_recharge(
            user_id=user["id"],
            openid=openid,
            points=package["points"],
            amount_cents=package["amount_cents"],
        )
        store = open_site_store(app.state.repo)
        try:
            store.create_payment_order(
                out_trade_no=payment["outTradeNo"],
                user_id=user["id"],
                points=int(package["points"]),
                amount_cents=int(package["amount_cents"]),
            )
        finally:
            store.close()
        return {"payment": payment, "package": package}

    @app.post("/site/me/recharge/wechatpay/confirm")
    def confirm_site_me_wechatpay_recharge(request: Request, body: ConfirmWechatPayRechargeRequest) -> dict:
        out_trade_no = body.out_trade_no.strip()
        if not out_trade_no:
            raise HTTPException(status_code=400, detail="out_trade_no is required.")
        store = open_site_store(app.state.repo)
        try:
            user = require_site_session_user(request, store)
            try:
                order = store.get_payment_order(out_trade_no)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Payment order not found.") from exc
            if order["user_id"] != user["id"]:
                raise HTTPException(status_code=404, detail="Payment order not found.")
            if order["status"] == "paid":
                return {"user": user, "order": order, "credited": False}
        finally:
            store.close()

        transaction = query_wechatpay_order(out_trade_no)
        trade_state = str(transaction.get("trade_state") or "")
        transaction_id = str(transaction.get("transaction_id") or "")
        amount = transaction.get("amount") or {}
        total = int(amount.get("total") or 0)
        if trade_state != "SUCCESS":
            store = open_site_store(app.state.repo)
            try:
                order = store.mark_payment_order_status(
                    out_trade_no=out_trade_no,
                    status=trade_state.lower() or "not_paid",
                    transaction_id=transaction_id,
                )
                return {"user": user, "order": order, "credited": False, "trade_state": trade_state}
            finally:
                store.close()
        if total != int(order["amount_cents"]):
            raise HTTPException(status_code=409, detail="Payment amount does not match local order.")
        store = open_site_store(app.state.repo)
        try:
            credited_user, credited = store.mark_payment_order_paid(
                out_trade_no=out_trade_no,
                transaction_id=transaction_id,
            )
            order = store.get_payment_order(out_trade_no)
            return {"user": credited_user, "order": order, "credited": credited, "trade_state": trade_state}
        finally:
            store.close()

    @app.get("/site/me/tasks")
    def list_site_me_tasks(request: Request) -> dict:
        store = open_site_store(app.state.repo)
        try:
            user = require_site_session_user(request, store)
            tasks = [enrich_site_task(app.state.repo, task) for task in store.list_user_tasks(user["id"])]
            return {"user": user, "tasks": tasks}
        finally:
            store.close()

    @app.get("/site/me/tasks/statuses")
    def list_site_me_task_statuses(request: Request) -> dict:
        """Return the minimum task state needed by polling clients."""
        store = open_site_store(app.state.repo)
        try:
            user = require_site_session_user(request, store)
            statuses = store.list_user_task_statuses(user["id"])
            revision = max((str(item.get("updated_at") or "") for item in statuses), default="")
            return {"statuses": statuses, "revision": revision}
        finally:
            store.close()

    @app.post("/site/me/tasks")
    async def submit_site_me_task(
        request: Request,
        file: UploadFile = File(...),
        source_name: str = Form(""),
    ) -> dict:
        store = open_site_store(app.state.repo)
        try:
            user = require_site_session_user(request, store)
        finally:
            store.close()
        return await submit_site_task_for_user(user["id"], file, source_name)

    @app.post("/site/me/tasks/direct-upload/init")
    def init_site_me_direct_upload(request: Request, body: DirectUploadInitRequest) -> dict:
        store = open_site_store(app.state.repo)
        try:
            user = require_site_session_user(request, store)
            task_id = store.next_id("task")
        finally:
            store.close()
        return init_site_direct_upload_for_user(user["id"], task_id, body)

    @app.post("/site/me/tasks/direct-upload/complete")
    def complete_site_me_direct_upload(request: Request, body: DirectUploadCompleteRequest) -> dict:
        store = open_site_store(app.state.repo)
        try:
            user = require_site_session_user(request, store)
        finally:
            store.close()
        return complete_site_direct_upload_for_user(user["id"], body)

    @app.get("/site/me/tasks/{task_id}")
    def get_site_me_task(request: Request, task_id: str) -> dict:
        store = open_site_store(app.state.repo)
        try:
            user = require_site_session_user(request, store)
            task = get_site_user_task_or_404(store, task_id, user["id"], detail=True)
            return {
                "task": enrich_site_task(app.state.repo, task),
                "notification_config": task_complete_subscription_config(),
            }
        finally:
            store.close()

    @app.get("/site/me/tasks/{task_id}/editor")
    def get_site_me_task_editor(request: Request, task_id: str) -> dict:
        store = open_site_store(app.state.repo)
        try:
            user = require_site_session_user(request, store)
            summary = get_site_user_task_or_404(store, task_id, user["id"], detail=True)
            task = store.get_task_editor(task_id)
            return {
                "task": enrich_site_task(app.state.repo, summary),
                "editor": {
                    "utterances": task["utterances"],
                },
            }
        finally:
            store.close()

    @app.post("/site/me/tasks/{task_id}/start")
    def start_site_me_task(request: Request, task_id: str, body: StartTaskRequest) -> dict:
        store = open_site_store(app.state.repo)
        try:
            user = require_site_session_user(request, store)
            get_site_user_task_or_404(store, task_id, user["id"])
        finally:
            store.close()
        return start_site_task_for_user(
            task_id,
            body.confirm_points,
            notify_on_complete=body.notify_on_complete,
            notification_template_id=body.notification_template_id,
            required_user_id=user["id"],
        )

    @app.patch("/site/me/tasks/{task_id}")
    def rename_site_me_task(request: Request, task_id: str, body: RenameTaskRequest) -> dict:
        title = body.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="title must not be empty.")
        store = open_site_store(app.state.repo)
        try:
            user = require_site_session_user(request, store)
            get_site_user_task_or_404(store, task_id, user["id"])
            task = store.rename_task(task_id, title)
            return {"task": task_summary_only(task)}
        finally:
            store.close()

    @app.post("/site/me/tasks/{task_id}/correction")
    def save_site_me_task_correction(request: Request, task_id: str, body: SaveCorrectionRequest) -> dict:
        store = open_site_store(app.state.repo)
        try:
            user = require_site_session_user(request, store)
            get_site_user_task_or_404(store, task_id, user["id"])
            task = store.save_correction(task_id, utterances=body.utterances)
            return {"task": task_summary_only(task)}
        finally:
            store.close()

    @app.delete("/site/me/tasks/{task_id}")
    def delete_site_me_task(request: Request, task_id: str) -> dict:
        store = open_site_store(app.state.repo)
        try:
            user = require_site_session_user(request, store)
            task = get_site_user_task_or_404(store, task_id, user["id"])
            delete_site_task_with_resources(app.state.repo, store, task)
            return {"ok": True, "task_id": task_id}
        finally:
            store.close()

    @app.get("/site/me/tasks/{task_id}/export")
    def export_site_me_task(request: Request, task_id: str, format: str = "srt") -> Response:
        store = open_site_store(app.state.repo)
        try:
            user = require_site_session_user(request, store)
            get_site_user_task_or_404(store, task_id, user["id"])
        finally:
            store.close()
        return build_site_task_export(task_id, format)

    @app.post("/site/users/{user_id}/recharge")
    def recharge_site_user(user_id: str, request: RechargePointsRequest) -> dict:
        if request.points <= 0:
            raise HTTPException(status_code=400, detail="points must be > 0.")
        store = open_site_store(app.state.repo)
        try:
            try:
                user = store.add_points(
                    user_id,
                    delta=request.points,
                    kind="recharge",
                    note=request.note.strip() or "manual recharge",
                )
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="User not found.") from exc
            return {"user": user}
        finally:
            store.close()

    @app.get("/site/users/{user_id}/tasks")
    def list_site_user_tasks(user_id: str) -> dict:
        store = open_site_store(app.state.repo)
        try:
            try:
                user = store.get_user(user_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="User not found.") from exc
            tasks = [enrich_site_task(app.state.repo, task) for task in store.list_user_tasks(user_id)]
            return {"user": user, "tasks": tasks}
        finally:
            store.close()

    @app.get("/site/tasks/{task_id}")
    def get_site_task(task_id: str) -> dict:
        store = open_site_store(app.state.repo)
        try:
            try:
                task = store.get_task_detail(task_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Task not found.") from exc
            return {"task": enrich_site_task(app.state.repo, task)}
        finally:
            store.close()

    @app.get("/site/tasks/{task_id}/editor")
    def get_site_task_editor(task_id: str) -> dict:
        store = open_site_store(app.state.repo)
        try:
            try:
                task = store.get_task_editor(task_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Task not found.") from exc
            summary = store.get_task_detail(task_id)
            return {
                "task": enrich_site_task(app.state.repo, summary),
                "editor": {
                    "utterances": task["utterances"],
                },
            }
        finally:
            store.close()

    @app.get("/site/tasks/{task_id}/export")
    def export_site_task(task_id: str, format: str = "srt") -> Response:
        return build_site_task_export(task_id, format)

    @app.post("/site/tasks/{task_id}/correction")
    def save_site_task_correction(task_id: str, request: SaveCorrectionRequest) -> dict:
        store = open_site_store(app.state.repo)
        try:
            try:
                task = store.save_correction(
                    task_id,
                    utterances=request.utterances,
                )
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Task not found.") from exc
            return {"task": task_summary_only(task)}
        finally:
            store.close()

    @app.post("/site/tasks/{task_id}/confirm")
    def confirm_site_task(task_id: str) -> dict:
        store = open_site_store(app.state.repo)
        try:
            try:
                task = store.confirm_result(task_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Task not found.") from exc
            return {"task": task_summary_only(task)}
        finally:
            store.close()

    @app.delete("/site/tasks/{task_id}")
    def delete_site_task(task_id: str) -> dict:
        store = open_site_store(app.state.repo)
        try:
            try:
                task = store.get_task(task_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Task not found.") from exc
            delete_site_task_with_resources(app.state.repo, store, task)
            return {"ok": True, "task_id": task_id}
        finally:
            store.close()

    @app.patch("/site/tasks/{task_id}")
    def rename_site_task(task_id: str, request: RenameTaskRequest) -> dict:
        title = request.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="title must not be empty.")
        store = open_site_store(app.state.repo)
        try:
            try:
                task = store.rename_task(task_id, title)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Task not found.") from exc
            return {"task": task_summary_only(task)}
        finally:
            store.close()

    @app.post("/site/tasks/{task_id}/start")
    def start_site_task(task_id: str, request: StartTaskRequest) -> dict:
        return start_site_task_for_user(
            task_id,
            request.confirm_points,
            notify_on_complete=request.notify_on_complete,
            notification_template_id=request.notification_template_id,
        )

    @app.get("/site/admin/meta")
    def site_admin_meta() -> dict:
        return {
            "environment": recordflow_environment(),
            "service_name": "RecordFlow",
            "server_time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    @app.post("/site/admin/users")
    def create_site_admin_user(request: AdminCreateUserRequest) -> dict:
        name = validate_admin_user_name(request.name)
        role = validate_admin_user_role(request.role)
        if request.initial_points < 0:
            raise HTTPException(status_code=400, detail="initial_points must be greater than or equal to 0.")
        store = open_site_store(app.state.repo)
        try:
            user = store.create_user(name, role=role)
            if request.initial_points:
                user = store.add_points(
                    user["id"],
                    delta=request.initial_points,
                    kind="admin_adjustment_credit",
                    note="initial points",
                )
            return {"user": user}
        finally:
            store.close()

    @app.patch("/site/admin/users/{user_id}")
    def update_site_admin_user(user_id: str, request: AdminUpdateUserRequest) -> dict:
        if request.name is None and request.role is None:
            raise HTTPException(status_code=400, detail="name or role is required.")
        store = open_site_store(app.state.repo)
        try:
            try:
                current = store.get_user(user_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="User not found.") from exc
            name = current["name"] if request.name is None else validate_admin_user_name(request.name)
            role = current["role"] if request.role is None else validate_admin_user_role(request.role)
            try:
                user = store.update_user(user_id, name=name, role=role)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="User not found.") from exc
            return {"user": user}
        finally:
            store.close()

    @app.post("/site/admin/users/{user_id}/points")
    def adjust_site_admin_user_points(user_id: str, request: AdminAdjustPointsRequest) -> dict:
        if request.delta == 0:
            raise HTTPException(status_code=400, detail="delta must not be 0.")
        kind = "admin_adjustment_credit" if request.delta > 0 else "admin_adjustment_debit"
        store = open_site_store(app.state.repo)
        try:
            try:
                user = store.add_points(
                    user_id,
                    delta=request.delta,
                    kind=kind,
                    note=request.note.strip() or "manual admin adjustment",
                )
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="User not found.") from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"user": user}
        finally:
            store.close()

    @app.get("/site/admin/dashboard")
    def site_admin_dashboard() -> dict:
        store = open_site_store(app.state.repo)
        try:
            return {
                "users": store.list_users(),
                "tasks": store.list_tasks(),
                "point_ledger": store.list_point_ledger(),
                "agreements": store.list_user_agreements(),
            }
        finally:
            store.close()

    @app.post("/site/users/{user_id}/tasks")
    async def submit_site_task(
        user_id: str,
        file: UploadFile = File(...),
        source_name: str = Form(""),
    ) -> dict:
        return await submit_site_task_for_user(user_id, file, source_name)

    async def submit_site_task_for_user(user_id: str, file: UploadFile, source_name: str = "") -> dict:
        filename = Path(source_name.strip() or file.filename or "recording.webm").name
        if not is_supported_site_task_audio(filename, file.content_type):
            raise HTTPException(
                status_code=400,
                detail="仅支持提交音频或视频文件，支持 mp3、m4a、wav、mp4、mov、ogg、webm、flac 等格式。",
            )
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        if len(data) > SITE_TASK_MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="音频文件不能超过 200MB。")
        workspace_id = get_or_create_site_workspace(app.state.repo)
        store = open_site_store(app.state.repo)
        try:
            try:
                store.get_user(user_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="User not found.") from exc
            task_id = store.next_id("task")
            local_path = pending_upload_path(task_id, filename)
            local_path.write_bytes(data)
            try:
                duration_seconds = probe_media_duration_seconds(local_path)
            except FileNotFoundError as exc:
                remove_local_file_if_exists(str(local_path))
                raise HTTPException(status_code=503, detail="ffprobe is not installed on the server.") from exc
            charge = estimate_task_charge(duration_seconds)
            task = store.create_pending_task(
                task_id=task_id,
                user_id=user_id,
                workspace_id=workspace_id,
                title=filename,
                source_name=filename,
                content_type=file.content_type or "application/octet-stream",
                original_size_bytes=len(data),
                duration_seconds=duration_seconds,
                points_cost=charge.points,
                charge_basis=charge.basis,
                agreement_version=AGREEMENT_VERSION,
                local_file_path=str(local_path),
            )
            if task["id"] != task_id:
                raise HTTPException(status_code=500, detail="Task creation id mismatch.")
            return {"task": task}
        finally:
            store.close()

    def init_site_direct_upload_for_user(user_id: str, task_id: str, body: DirectUploadInitRequest) -> dict:
        source_name = Path((body.source_name or "").strip() or "recording.mp3").name
        content_type = preferred_upload_content_type(source_name, body.content_type)
        if not is_supported_site_task_audio(source_name, content_type):
            raise HTTPException(
                status_code=400,
                detail="仅支持提交音频文件，支持 mp3、m4a、wav、ogg、webm、flac 等格式。",
            )
        if body.size_bytes is not None:
            size_bytes = int(body.size_bytes)
            if size_bytes <= 0:
                raise HTTPException(status_code=400, detail="Uploaded file is empty.")
            if size_bytes > SITE_TASK_MAX_AUDIO_BYTES:
                raise HTTPException(status_code=413, detail="音频文件不能超过 200MB。")
        try:
            settings = cos_direct_upload_settings()
        except COSDirectUploadConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        storage_filename = direct_upload_storage_filename(source_name, content_type)
        object_key = build_direct_upload_object_key(task_id, storage_filename, settings)
        now = int(time.time())
        ttl_seconds = direct_upload_ttl_seconds()
        expires_at = now + ttl_seconds
        upload_method = "POST"
        upload_url = settings.upload_url
        upload_headers = {}
        form_data = {
            "key": object_key,
            "success_action_status": "200",
            "Content-Type": content_type,
        }
        if not settings.public_write:
            key_time, policy, signature = build_cos_post_upload_policy(
                settings=settings,
                object_key=object_key,
                content_type=content_type,
                start_at=now,
                expires_at=expires_at,
            )
            form_data.update(
                {
                    "policy": policy,
                    "q-sign-algorithm": "sha1",
                    "q-ak": settings.secret_id,
                    "q-key-time": key_time,
                    "q-signature": signature,
                }
            )
        upload_token = create_direct_upload_token(
            {
                "user_id": user_id,
                "task_id": task_id,
                "source_name": source_name,
                "storage_filename": storage_filename,
                "content_type": content_type,
                "key": object_key,
                "exp": expires_at,
            }
        )
        return {
            "task_id": task_id,
            "upload_token": upload_token,
            "upload": {
                "method": upload_method,
                "url": upload_url,
                "headers": upload_headers,
                "file_field": "file",
                "form_data": form_data,
                "object_key": object_key,
                "object_url": direct_upload_object_url(settings, object_key),
                "expires_at": expires_at,
                "max_size_bytes": SITE_TASK_MAX_AUDIO_BYTES,
                "auth": "public-write" if settings.public_write else "signed-post",
            },
        }

    def complete_site_direct_upload_for_user(user_id: str, body: DirectUploadCompleteRequest) -> dict:
        payload = decode_direct_upload_token(body.upload_token)
        if payload["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Upload token does not match current user.")
        try:
            settings = cos_direct_upload_settings()
        except COSDirectUploadConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        task_id = payload["task_id"]
        storage_filename = payload["storage_filename"]
        expected_key = build_direct_upload_object_key(task_id, storage_filename, settings)
        if payload["key"] != expected_key:
            raise HTTPException(status_code=400, detail="Upload token does not match current storage path.")
        if body.object_key is not None and body.object_key != expected_key:
            raise HTTPException(status_code=400, detail="Completed object key does not match upload token.")
        workspace_id = get_or_create_site_workspace(app.state.repo)
        store = open_site_store(app.state.repo)
        try:
            try:
                store.get_user(user_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="User not found.") from exc
            try:
                existing = store.get_task(task_id)
            except KeyError:
                existing = None
            if existing is not None:
                if existing["user_id"] != user_id:
                    raise HTTPException(status_code=404, detail="Task not found.")
                return {"task": existing}
            local_path = pending_upload_path(task_id, storage_filename)
            if not local_path.exists() or not local_path.is_file():
                raise HTTPException(status_code=409, detail="Uploaded object is not visible on the server yet.")
            original_size_bytes = local_path.stat().st_size
            if original_size_bytes <= 0:
                remove_local_file_if_exists(str(local_path))
                raise HTTPException(status_code=400, detail="Uploaded file is empty.")
            if original_size_bytes > SITE_TASK_MAX_AUDIO_BYTES:
                remove_local_file_if_exists(str(local_path))
                raise HTTPException(status_code=413, detail="音频文件不能超过 200MB。")
            try:
                duration_seconds = probe_media_duration_seconds(local_path)
            except FileNotFoundError as exc:
                remove_local_file_if_exists(str(local_path))
                raise HTTPException(status_code=503, detail="ffprobe is not installed on the server.") from exc
            charge = estimate_task_charge(duration_seconds)
            task = store.create_pending_task(
                task_id=task_id,
                user_id=user_id,
                workspace_id=workspace_id,
                title=payload["source_name"],
                source_name=payload["source_name"],
                content_type=payload["content_type"],
                original_size_bytes=original_size_bytes,
                duration_seconds=duration_seconds,
                points_cost=charge.points,
                charge_basis=charge.basis,
                agreement_version=AGREEMENT_VERSION,
                local_file_path=str(local_path),
            )
            if task["id"] != task_id:
                raise HTTPException(status_code=500, detail="Task creation id mismatch.")
            return {"task": task}
        finally:
            store.close()

    def start_site_task_for_user(
        task_id: str,
        confirm_points: bool,
        notify_on_complete: bool = False,
        notification_template_id: str = "",
        required_user_id: str | None = None,
    ) -> dict:
        if not confirm_points:
            raise HTTPException(status_code=400, detail="confirm_points must be true.")

        resolved_template_id = ""
        if notify_on_complete:
            notification_config = task_complete_subscription_config()
            if not notification_config["enabled"]:
                raise HTTPException(status_code=503, detail="微信完成通知暂不可用。")
            requested_template_id = notification_template_id.strip()
            resolved_template_id = notification_config["template_id"]
            if not requested_template_id or requested_template_id != resolved_template_id:
                raise HTTPException(status_code=409, detail="通知模板已更新，请重新授权。")

        store = open_site_store(app.state.repo)
        try:
            try:
                task = store.get_task(task_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Task not found.") from exc
            if required_user_id and task["user_id"] != required_user_id:
                raise HTTPException(status_code=404, detail="Task not found.")
            if task["status"] != "uploaded":
                raise HTTPException(status_code=400, detail=f"Task status {task['status']} cannot be started.")
            local_file_path = task.get("local_file_path")
            if not local_file_path or not Path(local_file_path).exists():
                store.update_task_status(task_id, "expired", error="Local upload expired before confirmation.")
                raise HTTPException(status_code=410, detail="Local upload expired before confirmation.")
            try:
                task = store.mark_task_starting_with_points(
                    task_id,
                    task["user_id"],
                    notify_on_complete=notify_on_complete,
                    notification_template_id=resolved_template_id,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            job_id = app.state.repo.enqueue_site_task_prepare_job(task_id)
            return {
                "task": task_summary_only(task),
                "job": app.state.repo.get_job(job_id),
            }
        finally:
            store.close()

    def build_site_task_export(task_id: str, format: str) -> Response:
        export_format = format.strip().lower()
        if export_format not in {"srt", "text", "txt", "doc", "word"}:
            raise HTTPException(status_code=400, detail="format must be srt, text, or doc.")
        store = open_site_store(app.state.repo)
        try:
            try:
                task = store.get_task_editor(task_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Task not found.") from exc
            utterances = task["utterances"]
            if not utterances:
                raise HTTPException(status_code=400, detail="Task has no transcript to export.")
            if export_format == "srt":
                content = build_srt_export(utterances)
                extension = "srt"
                media_type = "application/x-subrip; charset=utf-8"
            elif export_format in {"doc", "word"}:
                content = build_doc_export(utterances)
                extension = "doc"
                media_type = "application/msword; charset=utf-8"
            else:
                content = build_text_export(utterances)
                extension = "txt"
                media_type = "text/plain; charset=utf-8"
            return Response(
                content=content,
                media_type=media_type,
                headers={"Content-Disposition": export_content_disposition(task["source_name"], extension)},
            )
        finally:
            store.close()

    async def upload_media_file(
        file: UploadFile,
        source_name: str,
        compressed: bool,
        original_size_bytes: int | None,
        compressed_size_bytes: int | None,
        compression_codec: str | None,
        duration_seconds: float | None,
    ) -> dict:
        filename = source_name.strip() or file.filename or "recording.webm"
        stored_filename = file.filename or filename
        if not is_supported_upload_media(stored_filename, file.content_type):
            raise HTTPException(
                status_code=400,
                detail="MVP accepts common audio/video uploads such as wav, mp3, m4a, webm, ogg, flac, mp4, or mov.",
            )
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        try:
            upload = upload_media_to_b2(
                data=data,
                source_name=stored_filename,
                content_type=file.content_type,
            )
        except B2ConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except B2UploadError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            **upload,
            "source_name": filename,
            "stored_name": stored_filename,
            "original_size_bytes": original_size_bytes,
            "compressed_size_bytes": compressed_size_bytes or len(data),
            "compression_codec": compression_codec,
            "client_compressed": compressed,
        }

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        try:
            job = app.state.repo.get_job(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found.") from exc
        response = {"job": job}
        if job.get("record_id"):
            try:
                response["digest"] = app.state.repo.get_record_digest(job["record_id"])
            except KeyError:
                pass
        return response

    @app.get("/workspaces/{workspace_id}/state")
    def get_state(
        workspace_id: str,
        type: str | None = None,
        status: str | None = None,
    ) -> dict:
        get_workspace_or_404(app.state.repo, workspace_id)
        state_objects = app.state.repo.list_state_objects(workspace_id)
        if type:
            state_objects = [item for item in state_objects if item.type.value == type]
        if status:
            state_objects = [item for item in state_objects if item.status == status]
        return {
            "state_objects": to_jsonable(state_objects),
            "change_events": to_jsonable(app.state.repo.list_change_events(workspace_id)),
        }

    @app.get("/workspaces/{workspace_id}/state/objects")
    def list_state_objects(
        workspace_id: str,
        type: str | None = None,
        status: str | None = None,
    ) -> dict:
        get_workspace_or_404(app.state.repo, workspace_id)
        state_objects = app.state.repo.list_state_objects(workspace_id)
        if type:
            state_objects = [item for item in state_objects if item.type.value == type]
        if status:
            state_objects = [item for item in state_objects if item.status == status]
        return {"state_objects": to_jsonable(state_objects)}

    @app.patch("/state/objects/{state_object_id}")
    def patch_state_object(state_object_id: str, request: StateObjectPatchRequest) -> dict:
        try:
            state_object, change_event = app.state.repo.patch_state_object(
                state_object_id,
                record_id=request.record_id,
                summary=request.summary,
                status=request.status,
                payload=request.payload,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="State object not found.") from exc
        return {
            "state_object": to_jsonable(state_object),
            "change_event": to_jsonable(change_event),
        }

    @app.post("/state/objects/{state_object_id}/archive")
    def archive_state_object(state_object_id: str) -> dict:
        try:
            state_object, change_event = app.state.repo.patch_state_object(
                state_object_id,
                record_id="user_archive",
                status="archived",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="State object not found.") from exc
        return {
            "state_object": to_jsonable(state_object),
            "change_event": to_jsonable(change_event),
        }

    @app.post("/state/objects/{state_object_id}/close")
    def close_state_object(state_object_id: str) -> dict:
        try:
            state_object, change_event = app.state.repo.patch_state_object(
                state_object_id,
                record_id="user_close",
                status="closed",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="State object not found.") from exc
        return {
            "state_object": to_jsonable(state_object),
            "change_event": to_jsonable(change_event),
        }

    @app.post("/state/objects/{state_object_id}/reopen")
    def reopen_state_object(state_object_id: str) -> dict:
        try:
            state_object, change_event = app.state.repo.patch_state_object(
                state_object_id,
                record_id="user_reopen",
                status="open",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="State object not found.") from exc
        return {
            "state_object": to_jsonable(state_object),
            "change_event": to_jsonable(change_event),
        }

    @app.post("/state/objects/{state_object_id}/clarify")
    def clarify_state_object(state_object_id: str, request: StateObjectClarifyRequest) -> dict:
        try:
            state_object = app.state.repo.get_state_object(state_object_id)
            clarifications = list(state_object.payload.get("clarifications", []))
            clarifications.append(request.note)
            state_object, change_event = app.state.repo.patch_state_object(
                state_object_id,
                record_id="user_clarify",
                payload={"clarifications": clarifications},
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="State object not found.") from exc
        return {
            "state_object": to_jsonable(state_object),
            "change_event": to_jsonable(change_event),
        }

    @app.get("/workspaces/{workspace_id}/review")
    def get_review(workspace_id: str) -> dict:
        get_workspace_or_404(app.state.repo, workspace_id)
        return {"review_items": to_jsonable(app.state.repo.list_review_items(workspace_id))}

    @app.post("/review/{change_event_id}")
    def update_review(change_event_id: str, request: ReviewUpdateRequest) -> dict[str, str]:
        try:
            app.state.repo.set_review_status(change_event_id, request.status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": change_event_id, "status": request.status}

    return app


def get_workspace_or_404(repo: object, workspace_id: str):
    try:
        return repo.workspaces[workspace_id]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workspace not found.") from exc


def build_dashboard(repo: object) -> dict:
    workspaces = to_jsonable(repo.list_workspaces())
    records = to_jsonable(repo.list_records()) if hasattr(repo, "list_records") else []
    media_index = {}
    if hasattr(repo, "list_workspaces") and hasattr(repo, "list_media_records"):
        for workspace in repo.list_workspaces():
            media_index[workspace.id] = to_jsonable(repo.list_media_records(workspace.id))
    records_by_workspace: dict[str, list[dict]] = {}
    for record in records:
        record_id = record["id"]
        workspace_id = record["workspace_id"]
        record_copy = dict(record)
        record_copy["digest"] = get_record_digest_or_none(repo, record_id)
        records_by_workspace.setdefault(workspace_id, []).append(record_copy)
    workspace_rows = []
    for workspace in workspaces:
        workspace_id = workspace["id"]
        workspace_rows.append(
            {
                **workspace,
                "records": records_by_workspace.get(workspace_id, []),
                "media": media_index.get(workspace_id, []),
                "state_objects": to_jsonable(repo.list_state_objects(workspace_id))
                if hasattr(repo, "list_state_objects")
                else [],
                "review_items": to_jsonable(repo.list_review_items(workspace_id))
                if hasattr(repo, "list_review_items")
                else [],
            }
        )
    return {"workspaces": workspace_rows, "record_count": len(records)}


def get_record_digest_or_none(repo: object, record_id: str):
    try:
        return repo.get_record_digest(record_id)
    except Exception:
        return None


def open_site_store(repo: object) -> ASRSiteStore:
    return ASRSiteStore(repo)


def get_or_create_site_workspace(repo: object) -> str:
    for workspace in repo.list_workspaces():
        if workspace.name == SITE_WORKSPACE_NAME:
            return workspace.id
    return repo.create_workspace(SITE_WORKSPACE_NAME, SITE_WORKSPACE_PROFILE)


def recharge_package_or_400(points: int) -> dict[str, int | str]:
    packages = {
        100: {"points": 100, "amount_cents": 100, "label": "100 点"},
        500: {"points": 500, "amount_cents": 500, "label": "500 点"},
        1000: {"points": 1000, "amount_cents": 1000, "label": "1000 点"},
    }
    package = packages.get(points)
    if package is not None:
        return package
    if points < 10 or points > 10000:
        raise HTTPException(status_code=400, detail="充值点数范围为 10-10000。")
    return {"points": points, "amount_cents": points, "label": f"{points} 点"}


def create_wechatpay_jsapi_recharge(
    *,
    user_id: str,
    openid: str,
    points: int,
    amount_cents: int,
) -> dict[str, str]:
    appid = os.getenv("WECHAT_MINIAPP_APPID", "").strip()
    mchid = os.getenv("WECHAT_PAY_MCH_ID", "").strip()
    serial_no = os.getenv("WECHAT_PAY_MCH_SERIAL_NO", "").strip()
    private_key_path = os.getenv("WECHAT_PAY_MCH_PRIVATE_KEY_PATH", "").strip()
    notify_url = os.getenv("WECHAT_PAY_NOTIFY_URL", "").strip() or "https://example.com/site/payments/wechat/notify"
    if not all([appid, mchid, serial_no, private_key_path]):
        raise_wechatpay_unavailable("missing jsapi recharge configuration")
    private_key_path = require_readable_wechatpay_private_key(private_key_path)

    out_trade_no = f"rf_{int(time.time())}_{secrets.token_hex(6)}"
    body = {
        "appid": appid,
        "mchid": mchid,
        "description": f"RecordFlow 充值 {points} 点",
        "out_trade_no": out_trade_no,
        "notify_url": notify_url,
        "amount": {"total": amount_cents, "currency": "CNY"},
        "payer": {"openid": openid},
        "attach": json.dumps({"user_id": user_id, "points": points}, ensure_ascii=False),
    }
    response = wechatpay_v3_request(
        method="POST",
        path="/v3/pay/transactions/jsapi",
        body=body,
        mchid=mchid,
        serial_no=serial_no,
        private_key_path=private_key_path,
    )
    prepay_id = response.get("prepay_id")
    if not prepay_id:
        raise_wechatpay_unavailable("prepay_id missing from WeChat Pay response")

    timestamp = str(int(time.time()))
    nonce_str = secrets.token_hex(16)
    package_value = f"prepay_id={prepay_id}"
    pay_sign = wechatpay_sign(
        "\n".join([appid, timestamp, nonce_str, package_value, ""]),
        private_key_path,
    )
    return {
        "timeStamp": timestamp,
        "nonceStr": nonce_str,
        "package": package_value,
        "signType": "RSA",
        "paySign": pay_sign,
        "outTradeNo": out_trade_no,
    }


def query_wechatpay_order(out_trade_no: str) -> dict:
    mchid = os.getenv("WECHAT_PAY_MCH_ID", "").strip()
    serial_no = os.getenv("WECHAT_PAY_MCH_SERIAL_NO", "").strip()
    private_key_path = os.getenv("WECHAT_PAY_MCH_PRIVATE_KEY_PATH", "").strip()
    if not all([mchid, serial_no, private_key_path]):
        raise_wechatpay_unavailable("missing order query configuration")
    private_key_path = require_readable_wechatpay_private_key(private_key_path)
    path = f"/v3/pay/transactions/out-trade-no/{quote(out_trade_no)}?mchid={quote(mchid)}"
    return wechatpay_v3_request(
        method="GET",
        path=path,
        body=None,
        mchid=mchid,
        serial_no=serial_no,
        private_key_path=private_key_path,
    )


def wechatpay_v3_request(
    *,
    method: str,
    path: str,
    body: dict | None,
    mchid: str,
    serial_no: str,
    private_key_path: str,
) -> dict:
    body_text = "" if body is None else json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    timestamp = str(int(time.time()))
    nonce_str = secrets.token_hex(16)
    message = "\n".join([method, path, timestamp, nonce_str, body_text, ""])
    signature = wechatpay_sign(message, private_key_path)
    authorization = (
        'WECHATPAY2-SHA256-RSA2048 '
        f'mchid="{mchid}",nonce_str="{nonce_str}",signature="{signature}",'
        f'timestamp="{timestamp}",serial_no="{serial_no}"'
    )
    request = UrlRequest(
        f"https://api.mch.weixin.qq.com{path}",
        data=body_text.encode("utf-8") if body is not None else None,
        method=method,
        headers={
            "Authorization": authorization,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "RecordFlow/0.1",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise_wechatpay_unavailable(f"WeChat Pay request failed: {detail}", exc)
    return json.loads(payload or "{}")


def require_readable_wechatpay_private_key(private_key_path: str) -> str:
    try:
        key_path = Path(private_key_path)
        if not key_path.exists():
            raise_wechatpay_unavailable("private key path does not exist")
        if not key_path.is_file():
            raise_wechatpay_unavailable("private key path is not a file")
        if not os.access(key_path, os.R_OK):
            raise_wechatpay_unavailable("private key path is not readable")
    except OSError as exc:
        raise_wechatpay_unavailable("private key path cannot be checked", exc)
    return str(key_path)


def raise_wechatpay_unavailable(reason: str, exc: Exception | None = None) -> None:
    LOGGER.warning("WeChat Pay unavailable: %s", reason, exc_info=exc)
    raise HTTPException(status_code=503, detail=WECHATPAY_UNAVAILABLE_DETAIL)


def wechatpay_sign(message: str, private_key_path: str) -> str:
    process = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", private_key_path],
        input=message.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        error = process.stderr.decode("utf-8", errors="replace").strip()
        raise_wechatpay_unavailable(f"WeChat Pay signing failed: {error}")
    return base64.b64encode(process.stdout).decode("ascii")


def exchange_wechat_code_for_session(*, appid: str, secret: str, code: str) -> dict:
    query = urlencode(
        {
            "appid": appid,
            "secret": secret,
            "js_code": code,
            "grant_type": "authorization_code",
        }
    )
    url = f"https://api.weixin.qq.com/sns/jscode2session?{query}"
    try:
        with urlopen(url, timeout=10) as response:
            payload = response.read().decode("utf-8")
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Failed to call WeChat code2Session.") from exc
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="Invalid response from WeChat code2Session.") from exc
    errcode = data.get("errcode")
    if errcode not in (None, 0):
        errmsg = data.get("errmsg") or "WeChat code2Session failed."
        raise HTTPException(status_code=401, detail=f"WeChat login failed ({errcode}): {errmsg}")
    return data


def build_doc_export(utterances: list[dict]) -> str:
    paragraphs = []
    for utterance in utterances:
        text = html_escape(str(utterance.get("text") or ""))
        if text:
            paragraphs.append(f"<p>{text}</p>")
    body = "\n".join(paragraphs)
    return (
        "<html><head><meta charset=\"utf-8\"></head>"
        "<body>"
        f"{body}"
        "</body></html>"
    )


def html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def site_session_ttl_seconds() -> int:
    return max(60, int(os.getenv("RECORDFLOW_SITE_SESSION_TTL_SECONDS", "2592000") or "2592000"))


def validate_agreement_acceptance(accepted: bool, agreement_version: str) -> str | None:
    version = str(agreement_version or "").strip()
    if not accepted and not version and not agreement_acceptance_required():
        return None
    if not accepted:
        raise HTTPException(status_code=400, detail="请先阅读并同意用户协议与隐私说明。")
    if version != AGREEMENT_VERSION:
        raise HTTPException(
            status_code=409,
            detail=f"用户协议与隐私说明已更新，请阅读并同意 {AGREEMENT_VERSION} 版本。",
        )
    return version


def agreement_acceptance_required() -> bool:
    value = os.getenv("RECORDFLOW_REQUIRE_AGREEMENT", "true")
    return value.strip().lower() not in {"0", "false", "no", "off"}


def site_session_secret() -> str:
    configured = os.getenv("RECORDFLOW_SESSION_SECRET", "").strip()
    if configured:
        return configured
    if is_production_environment():
        raise RuntimeError("RECORDFLOW_SESSION_SECRET is required in production.")
    return (
        os.getenv("SESSION_SECRET")
        or os.getenv("RECORDFLOW_APP_API_KEY")
        or "recordflow-local-session-secret"
    )


def validate_site_session_configuration() -> None:
    if is_production_environment():
        site_session_secret()
        if not os.getenv("RECORDFLOW_APP_API_KEY", "").strip():
            raise RuntimeError("RECORDFLOW_APP_API_KEY is required in production for admin APIs.")


def recordflow_environment() -> str:
    value = (
        os.getenv("RECORDFLOW_ENV")
        or os.getenv("ENVIRONMENT")
        or os.getenv("APP_ENV")
        or "development"
    )
    return value.strip().lower() or "development"


def is_production_environment() -> bool:
    return recordflow_environment() in {"production", "prod"}


def validate_admin_user_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise HTTPException(status_code=400, detail="User name is required.")
    return value


def validate_admin_user_role(role: str) -> str:
    value = role.strip().lower()
    if value not in {"user", "admin"}:
        raise HTTPException(status_code=400, detail="role must be user or admin.")
    return value


def create_site_session_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": int(time.time()) + site_session_ttl_seconds(),
    }
    body = encode_token_part(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = sign_site_session_body(body)
    return f"rf1.{body}.{signature}"


def create_direct_upload_token(payload: dict) -> str:
    body = encode_token_part(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = sign_site_session_body(body)
    return f"rfdu1.{body}.{signature}"


def decode_direct_upload_token(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "rfdu1":
        raise HTTPException(status_code=401, detail="Invalid direct upload token.")
    _, body, signature = parts
    expected = sign_site_session_body(body)
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid direct upload token.")
    try:
        payload = json.loads(decode_token_part(body).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid direct upload token.") from exc
    if int(payload.get("exp") or 0) < int(time.time()):
        raise HTTPException(status_code=401, detail="Direct upload token expired.")
    for key in ["user_id", "task_id", "source_name", "storage_filename", "content_type", "key"]:
        if not isinstance(payload.get(key), str) or not payload[key]:
            raise HTTPException(status_code=401, detail="Invalid direct upload token.")
    return payload


def decode_site_session_token(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "rf1":
        raise HTTPException(status_code=401, detail="Invalid site session token.")
    _, body, signature = parts
    expected = sign_site_session_body(body)
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid site session token.")
    try:
        payload = json.loads(decode_token_part(body).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid site session token.") from exc
    if int(payload.get("exp") or 0) < int(time.time()):
        raise HTTPException(status_code=401, detail="Site session token expired.")
    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="Invalid site session token.")
    return payload


def require_site_session_user(request: Request, store: ASRSiteStore) -> dict:
    token = site_session_token_from_request(request)
    payload = decode_site_session_token(token)
    try:
        return store.get_user(payload["sub"])
    except KeyError as exc:
        raise HTTPException(status_code=401, detail="Site session user not found.") from exc


POINT_LEDGER_TITLES = {
    "seed": "赠送",
    "signup_bonus": "注册赠送",
    "dev_signup_bonus": "注册赠送",
    "recharge": "充值",
    "wechatpay_recharge": "微信充值",
    "consume": "转写消耗",
    "transcription_refund": "转写退还",
    "admin_adjustment_credit": "后台发放",
    "admin_adjustment_debit": "后台扣减",
}


def public_point_ledger_entry(entry: dict) -> dict:
    kind = str(entry.get("kind") or "")
    public_entry = dict(entry)
    public_entry["display_title"] = POINT_LEDGER_TITLES.get(kind, "点数变动")
    if kind in {"signup_bonus", "dev_signup_bonus", "seed"}:
        public_entry["display_note"] = "系统赠送点数"
    elif kind in {"recharge", "wechatpay_recharge"}:
        public_entry["display_note"] = "充值点数已到账"
    elif kind == "consume":
        public_entry["display_note"] = "转写任务扣点"
    elif kind == "transcription_refund":
        public_entry["display_note"] = "转写任务异常退还"
    else:
        public_entry["display_note"] = str(entry.get("note") or "点数调整")
    return public_entry


def encode_point_ledger_cursor(entry: dict) -> str:
    created_at = entry.get("created_at")
    if hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    payload = json.dumps(
        {"created_at": str(created_at or ""), "id": str(entry.get("id") or "")},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_point_ledger_cursor(cursor: str) -> tuple[str | None, str | None]:
    if not cursor:
        return None, None
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding).decode("utf-8"))
        created_at = payload.get("created_at")
        entry_id = payload.get("id")
        if not isinstance(created_at, str) or not created_at or not isinstance(entry_id, str) or not entry_id:
            raise ValueError
        return created_at, entry_id
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError, base64.binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="Invalid point ledger cursor.") from exc


def is_supported_site_task_audio(filename: str, content_type: str | None) -> bool:
    suffix = Path(filename.lower()).suffix
    mime_type = (content_type or "").split(";", 1)[0].strip().lower()
    return mime_type in SITE_TASK_AUDIO_MIME_TYPES or suffix in SITE_TASK_AUDIO_EXTENSIONS


def direct_upload_ttl_seconds() -> int:
    return max(60, int(os.getenv("RECORDFLOW_DIRECT_UPLOAD_TTL_SECONDS", "900") or "900"))


def preferred_upload_content_type(filename: str, content_type: str | None) -> str:
    mime_type = (content_type or "").split(";", 1)[0].strip().lower()
    if mime_type and mime_type != "application/octet-stream":
        return mime_type
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def direct_upload_storage_filename(source_name: str, content_type: str | None) -> str:
    name = Path(source_name or "recording").name or "recording"
    suffix = Path(name).suffix.lower()
    if not suffix:
        suffix = audio_extension_for_content_type(content_type)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name).stem).strip(".-")
    if not stem:
        stem = "recording"
    stem = stem[:64].strip(".-") or "recording"
    digest = hashlib.sha1(f"{name}:{secrets.token_hex(8)}".encode("utf-8")).hexdigest()[:12]
    return f"{stem}-{digest}{suffix}"


def audio_extension_for_content_type(content_type: str | None) -> str:
    mime_type = (content_type or "").split(";", 1)[0].strip().lower()
    return {
        "audio/aac": ".aac",
        "audio/aiff": ".aiff",
        "audio/flac": ".flac",
        "audio/mp4": ".m4a",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/ogg": ".ogg",
        "audio/opus": ".opus",
        "audio/pcm": ".pcm",
        "audio/wav": ".wav",
        "audio/wave": ".wav",
        "audio/webm": ".webm",
        "audio/x-aiff": ".aiff",
        "audio/x-m4a": ".m4a",
        "audio/x-wav": ".wav",
    }.get(mime_type, ".bin")


def cos_direct_upload_settings() -> COSDirectUploadSettings:
    public_base_url = os.getenv("RECORDFLOW_PENDING_UPLOAD_PUBLIC_BASE_URL", "").strip().rstrip("/")
    parsed_public_base = urlparse(public_base_url) if public_base_url else None
    derived_bucket, derived_region = derive_cos_bucket_region(parsed_public_base)
    public_write = env_bool("RECORDFLOW_COS_DIRECT_UPLOAD_PUBLIC_WRITE", default=False)
    secret_id = (
        os.getenv("RECORDFLOW_COS_SECRET_ID")
        or os.getenv("TENCENTCLOUD_SECRET_ID")
        or os.getenv("COS_SECRET_ID")
        or ""
    ).strip()
    secret_key = (
        os.getenv("RECORDFLOW_COS_SECRET_KEY")
        or os.getenv("TENCENTCLOUD_SECRET_KEY")
        or os.getenv("COS_SECRET_KEY")
        or ""
    ).strip()
    bucket = (os.getenv("RECORDFLOW_COS_BUCKET") or derived_bucket or "").strip()
    region = (os.getenv("RECORDFLOW_COS_REGION") or derived_region or "").strip()
    key_prefix = (
        os.getenv("RECORDFLOW_COS_DIRECT_UPLOAD_PREFIX", "").strip().strip("/")
        or derive_cos_key_prefix(parsed_public_base)
        or derive_cos_key_prefix_from_pending_root()
    )
    upload_url = os.getenv("RECORDFLOW_COS_UPLOAD_URL", "").strip().rstrip("/")
    missing = [
        name
        for name, value in [
            ("RECORDFLOW_COS_BUCKET", bucket),
            ("RECORDFLOW_COS_REGION", region),
        ]
        if not value
    ]
    if not public_write:
        missing.extend(
            [
                name
                for name, value in [
                    ("TENCENTCLOUD_SECRET_ID", secret_id),
                    ("TENCENTCLOUD_SECRET_KEY", secret_key),
                ]
                if not value
            ]
        )
    if missing:
        raise COSDirectUploadConfigurationError(
            "COS direct upload is not configured. Missing: " + ", ".join(missing)
        )
    if not upload_url:
        upload_url = f"https://{bucket}.cos.{region}.myqcloud.com"
    if not public_base_url:
        public_base_url = upload_url
    return COSDirectUploadSettings(
        secret_id=secret_id,
        secret_key=secret_key,
        bucket=bucket,
        region=region,
        upload_url=upload_url,
        key_prefix=key_prefix,
        public_base_url=public_base_url,
        public_write=public_write,
    )


def env_bool(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def derive_cos_bucket_region(parsed_public_base) -> tuple[str, str]:
    if not parsed_public_base or not parsed_public_base.netloc:
        return "", ""
    host_parts = parsed_public_base.netloc.split(".")
    if len(host_parts) >= 4 and host_parts[1] in {"cos", "cos-website"}:
        return host_parts[0], host_parts[2]
    return "", ""


def derive_cos_key_prefix(parsed_public_base) -> str:
    if not parsed_public_base:
        return ""
    return parsed_public_base.path.strip("/")


def derive_cos_key_prefix_from_pending_root() -> str:
    root = pending_upload_root()
    try:
        return str(root.resolve().relative_to(Path("/record").resolve())).replace(os.sep, "/").strip("/")
    except ValueError:
        return "pending"


def build_direct_upload_object_key(
    task_id: str,
    storage_filename: str,
    settings: COSDirectUploadSettings,
) -> str:
    object_name = f"{task_id}-{Path(storage_filename).name}"
    return f"{settings.key_prefix}/{object_name}" if settings.key_prefix else object_name


def direct_upload_object_url(settings: COSDirectUploadSettings, object_key: str) -> str:
    prefix = settings.key_prefix.strip("/")
    object_name = object_key
    if prefix and object_key.startswith(f"{prefix}/"):
        object_name = object_key[len(prefix) + 1 :]
    if settings.public_base_url:
        return f"{settings.public_base_url.rstrip('/')}/{quote(object_name, safe='/')}"
    return f"{settings.upload_url.rstrip('/')}/{quote(object_key, safe='/')}"


def build_cos_put_upload_request(
    *,
    settings: COSDirectUploadSettings,
    object_key: str,
    content_type: str,
    start_at: int,
    expires_at: int,
) -> tuple[str, dict[str, str]]:
    key_time = f"{start_at};{expires_at}"
    host = f"{settings.bucket}.cos.{settings.region}.myqcloud.com"
    encoded_key = url_quote(object_key, safe="/")
    encoded_content_type = url_quote(content_type, safe="")
    http_string = "\n".join(
        [
            "put",
            f"/{encoded_key}",
            "",
            f"content-type={encoded_content_type}&host={host}",
            "",
        ]
    )
    string_to_sign = "\n".join(
        [
            "sha1",
            key_time,
            hashlib.sha1(http_string.encode("utf-8")).hexdigest(),
            "",
        ]
    )
    sign_key = hmac.new(settings.secret_key.encode("utf-8"), key_time.encode("utf-8"), hashlib.sha1).hexdigest()
    signature = hmac.new(sign_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).hexdigest()
    authorization = "&".join(
        [
            "q-sign-algorithm=sha1",
            f"q-ak={settings.secret_id}",
            f"q-sign-time={key_time}",
            f"q-key-time={key_time}",
            "q-header-list=content-type;host",
            "q-url-param-list=",
            f"q-signature={signature}",
        ]
    )
    return (
        f"https://{host}/{encoded_key}",
        {
            "Authorization": authorization,
            "Content-Type": content_type,
        },
    )


def build_cos_post_upload_policy(
    *,
    settings: COSDirectUploadSettings,
    object_key: str,
    content_type: str,
    start_at: int,
    expires_at: int,
) -> tuple[str, str, str]:
    key_time = f"{start_at};{expires_at}"
    policy_document = {
        "expiration": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(expires_at)),
        "conditions": [
            {"bucket": settings.bucket},
            {"key": object_key},
            {"success_action_status": "200"},
            {"Content-Type": content_type},
            {"q-sign-algorithm": "sha1"},
            {"q-ak": settings.secret_id},
            {"q-sign-time": key_time},
            ["content-length-range", 1, SITE_TASK_MAX_AUDIO_BYTES],
        ],
    }
    policy_text = json.dumps(policy_document, separators=(",", ":"), ensure_ascii=False)
    policy = base64.b64encode(policy_text.encode("utf-8")).decode("ascii")
    sign_key = hmac.new(settings.secret_key.encode("utf-8"), key_time.encode("utf-8"), hashlib.sha1).hexdigest()
    string_to_sign = hashlib.sha1(policy_text.encode("utf-8")).hexdigest()
    signature = hmac.new(sign_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).hexdigest()
    return key_time, policy, signature


def site_session_token_from_request(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return token
    token = request.headers.get("X-Site-Token", "").strip()
    if token:
        return token
    token = request.query_params.get("site_token", "").strip()
    if token:
        log_deprecated_query_token(request)
        return token
    raise HTTPException(status_code=401, detail="Missing site session token.")


def sign_site_session_body(body: str) -> str:
    digest = hmac.new(site_session_secret().encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    return encode_token_part(digest)


def encode_token_part(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def decode_token_part(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def get_site_user_task_or_404(
    store: ASRSiteStore,
    task_id: str,
    user_id: str,
    *,
    detail: bool = False,
) -> dict:
    try:
        task = store.get_task_detail(task_id) if detail else store.get_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found.") from exc
    if task["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


def delete_site_task_with_resources(
    repo: object,
    store: ASRSiteStore,
    task: dict,
) -> None:
    task_id = task["id"]
    try:
        current_task = store.get_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found.") from exc
    if current_task["status"] in SITE_TASK_ACTIVE_DELETE_STATUSES:
        raise HTTPException(status_code=409, detail="任务正在处理中，暂时无法删除。")

    media_id = current_task.get("media_id")
    media = None
    if media_id:
        try:
            media = repo.get_media_record(media_id)
        except KeyError:
            media = None

    local_file_path = current_task.get("local_file_path")
    if local_file_path:
        try:
            Path(local_file_path).unlink(missing_ok=True)
        except OSError as exc:
            LOGGER.exception("Failed to delete local upload for site task %s", task_id)
            raise HTTPException(
                status_code=500,
                detail="本地上传文件删除失败，任务未删除，请稍后重试。",
            ) from exc

    object_name = media.get("object_name") if media else None
    if object_name:
        try:
            delete_media_from_b2(object_name)
        except Exception as exc:
            LOGGER.exception("Failed to delete stored media for site task %s", task_id)
            raise HTTPException(
                status_code=502,
                detail="媒体文件删除失败，任务未删除，请稍后重试。",
            ) from exc

    try:
        deleted_task = store.delete_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found.") from exc
    deleted_media_id = deleted_task.get("media_id") or media_id
    if deleted_media_id:
        try:
            repo.delete_media_record(deleted_media_id)
        except KeyError:
            pass
        except Exception as exc:
            LOGGER.exception("Failed to delete media record for site task %s", task_id)
            raise HTTPException(
                status_code=500,
                detail="任务记录已删除，但关联媒体数据清理失败，请联系管理员。",
            ) from exc


def probe_media_duration_seconds(file_path: Path) -> float:
    process = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(file_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        error = (process.stderr or process.stdout or "").strip()
        remove_local_file_if_exists(str(file_path))
        raise HTTPException(status_code=400, detail=f"ffprobe failed to read duration: {error}")
    text = (process.stdout or "").strip()
    try:
        value = float(text)
    except ValueError as exc:
        remove_local_file_if_exists(str(file_path))
        raise HTTPException(status_code=400, detail="Could not parse media duration.") from exc
    if value <= 0:
        remove_local_file_if_exists(str(file_path))
        raise HTTPException(status_code=400, detail="Media duration must be greater than zero.")
    return value


def default_frontend_dist() -> Path:
    return Path(__file__).resolve().parent.parent / "frontend" / "dist"


def export_content_disposition(source_name: str, extension: str) -> str:
    safe_name = Path(source_name or "transcript").name
    stem = Path(safe_name).stem.strip() or "transcript"
    filename = f"{stem}.{extension}"
    ascii_fallback = "".join(char if char.isascii() and char not in {'"', "\\", ";"} else "_" for char in filename)
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"


def enrich_site_task(repo: object, task: dict) -> dict:
    if "media" in task:
        return task
    media_id = task.get("media_id")
    media = None
    if media_id and hasattr(repo, "get_media_record"):
        try:
            media = site_media_summary(repo.get_media_record(media_id))
        except KeyError:
            media = None
    return {
        **task,
        "media": media,
    }


def task_summary_only(task: dict) -> dict:
    return {
        key: value
        for key, value in task.items()
        if key not in {"transcript_text", "corrected_text", "utterances", "raw_result", "words"}
    }


def site_media_summary(media: dict | None) -> dict | None:
    if not media:
        return None
    return {
        key: value
        for key, value in media.items()
        if key
        in {
            "id",
            "source_name",
            "stored_name",
            "url",
            "public_url",
            "content_type",
            "status",
            "created_at",
            "updated_at",
        }
    }

if os.getenv("RECORDFLOW_SKIP_DEFAULT_APP", "").lower() not in {"1", "true", "yes"}:
    app = create_app()
