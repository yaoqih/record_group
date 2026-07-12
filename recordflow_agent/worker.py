from __future__ import annotations

import argparse
import logging
import os
import ssl
import subprocess
import tempfile
import time
from http.client import RemoteDisconnected
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.request import Request

from recordflow_agent.asr_site import ASRSiteStore, build_editable_utterances, remove_local_file_if_exists
from recordflow_agent.asr_client import (
    STEPFUN_MAX_AUDIO_DATA_BYTES,
    StepFunASRClient,
    is_stepfun_file_audio,
    is_stepfun_remuxable_audio,
    request_bytes,
)
from recordflow_agent.cli import build_digest_renderer, build_extractor
from recordflow_agent.media_storage import (
    B2UploadError,
    build_authorized_download_url,
    delete_media_from_b2,
    upload_media_to_b2,
)
from recordflow_agent.pipeline import process_record
from recordflow_agent.profiles import load_profile
from recordflow_agent.repository_factory import create_repository
from recordflow_agent.sqlite_repository import SQLiteRepository
from recordflow_agent.wechat_subscribe import send_task_complete_subscription


LOGGER = logging.getLogger(__name__)
QUEUE_MAINTENANCE_INTERVAL_SECONDS = 300.0


class SiteTaskExpiredError(RuntimeError):
    pass


def process_next_job(repo: object, job_types: set[str] | None = None) -> bool:
    job = repo.claim_next_job(job_types=job_types)
    if job is None:
        return False
    payload = job["payload"]
    try:
        if job["type"] == "compress_media":
            process_media_compression_job(repo, job)
        elif job["type"] == "prepare_site_task":
            process_site_task_prepare_job(repo, job)
        elif job["type"] == "transcribe_media":
            process_media_transcription_job(repo, job)
        elif job["type"] == "send_site_notification":
            process_site_notification_job(repo, job)
        elif job["type"] == "cleanup_expired_media":
            process_cleanup_expired_media_job(repo, job)
        else:
            process_record_job(repo, job)
    except Exception as exc:
        if job["type"] == "send_site_notification":
            task_id = payload.get("task_id")
            if task_id:
                try:
                    with open_site_store_if_available(repo) as store:
                        if store is not None:
                            store.mark_task_notification_failed(task_id, str(exc))
                except Exception:
                    LOGGER.exception(
                        "Could not persist notification failure for task %s.",
                        task_id,
                    )
            repo.fail_job(job["id"], str(exc))
            LOGGER.warning(
                "Completion subscription failed for task %s.",
                task_id,
                exc_info=True,
            )
            return True
        repo.fail_job(job["id"], str(exc))
        media_id = payload.get("media_id")
        if media_id:
            repo.update_media_status(media_id, "failed", error=str(exc))
            with open_site_store_if_available(repo) as store:
                if store is not None:
                    store.update_task_status_by_media_id(media_id, "failed", error=str(exc))
        task_id = payload.get("task_id")
        if task_id and not isinstance(exc, SiteTaskExpiredError):
            with open_site_store_if_available(repo) as store:
                if store is not None:
                    store.update_task_status(task_id, "failed", error=str(exc))
    return True


def process_record_job(repo: object, job: dict) -> None:
    payload = job["payload"]
    workspace = repo.workspaces[payload["workspace_id"]]
    profile = load_profile(workspace.profile)
    digest = process_record(
        repo=repo,
        workspace_id=payload["workspace_id"],
        profile=profile,
        title=payload["title"],
        text=payload["text"],
        extractor=build_extractor(bool(payload.get("use_llm"))),
        digest_renderer=build_digest_renderer(bool(payload.get("use_llm"))),
    )
    repo.complete_job(job["id"], digest.record_id)


def process_site_notification_job(repo: object, job: dict) -> None:
    task_id = job["payload"]["task_id"]
    store = ASRSiteStore(repo)
    try:
        try:
            task = store.begin_task_notification(task_id)
        except KeyError:
            task = None
        if task is None:
            repo.complete_job(job["id"], task_id)
            return
        appid = os.getenv("WECHAT_MINIAPP_APPID", "").strip()
        openid = store.get_user_wechat_openid(task["user_id"], appid)
    finally:
        store.close()

    if not openid:
        raise RuntimeError("No WeChat openid is available for the task owner.")
    if not send_task_complete_subscription(openid=openid, task=task):
        raise RuntimeError("WeChat task completion subscriptions are disabled.")

    store = ASRSiteStore(repo)
    try:
        try:
            store.mark_task_notification_sent(task_id)
        except KeyError:
            pass
    finally:
        store.close()
    repo.complete_job(job["id"], task_id)
    LOGGER.info("Completion subscription sent for task %s.", task_id)


def process_media_compression_job(repo: object, job: dict) -> None:
    payload = job["payload"]
    media = repo.get_media_record(payload["media_id"])
    repo.update_media_status(media["id"], "compressing")
    download_url = build_authorized_download_url(media["object_name"])
    data = request_bytes(Request(download_url, method="GET"), 300)
    compressed = compress_audio_for_asr(data, media["stored_name"], media["content_type"])
    if len(compressed) > STEPFUN_MAX_AUDIO_DATA_BYTES:
        raise ValueError("StepAudio 2.5 ASR SSE audio.data limit is 40MiB after backend compression.")
    compressed_name = compressed_filename(media["stored_name"])
    upload = upload_media_to_b2_with_retry(
        data=compressed,
        source_name=compressed_name,
        content_type="audio/ogg",
    )
    repo.replace_media_object(
        media["id"],
        stored_name=compressed_name,
        url=upload["url"],
        public_url=upload["public_url"],
        object_name=upload["object_name"],
        content_type=upload["content_type"],
        compressed_size_bytes=upload["size_bytes"],
        compression_codec="audio/ogg;codecs=opus",
    )
    repo.enqueue_media_transcription_job(
        workspace_id=payload["workspace_id"],
        media_id=media["id"],
        title=payload["title"],
        use_llm=bool(payload.get("use_llm")),
    )
    repo.complete_job(job["id"], media["id"])


def process_site_task_prepare_job(repo: object, job: dict) -> None:
    task_id = job["payload"]["task_id"]
    store = ASRSiteStore(repo)
    try:
        task = store.get_task(task_id)
    finally:
        store.close()
    if task["status"] != "starting":
        raise ValueError(f"Task status {task['status']} cannot be prepared.")
    local_file_path = task.get("local_file_path")
    if not local_file_path or not Path(local_file_path).exists():
        store = ASRSiteStore(repo)
        try:
            store.update_task_status(task_id, "expired", error="Local upload expired before preparation.")
        finally:
            store.close()
        raise SiteTaskExpiredError("Local upload expired before preparation.")

    source_bytes = Path(local_file_path).read_bytes()
    compressed = compress_audio_for_asr(source_bytes, task["source_name"], task["content_type"])
    compressed_name = compressed_filename(task["source_name"])
    upload = upload_media_to_b2_with_retry(
        data=compressed,
        source_name=compressed_name,
        content_type="audio/ogg",
    )
    media_id = repo.add_media_record(
        workspace_id=task["workspace_id"],
        source_name=task["source_name"],
        stored_name=compressed_name,
        url=upload["url"],
        public_url=upload["public_url"],
        object_name=upload["object_name"],
        content_type=upload["content_type"],
        original_size_bytes=task["original_size_bytes"],
        compressed_size_bytes=upload["size_bytes"],
        compression_codec="audio/ogg;codecs=opus",
    )
    transcription_job_id = repo.enqueue_media_transcription_job(
        workspace_id=task["workspace_id"],
        media_id=media_id,
        title=task["title"],
        use_llm=False,
    )
    remove_local_file_if_exists(local_file_path)
    store = ASRSiteStore(repo)
    try:
        store.attach_task_media_job(task_id, media_id, transcription_job_id)
    finally:
        store.close()
    repo.complete_job(job["id"], media_id)


def process_media_transcription_job(repo: object, job: dict) -> None:
    payload = job["payload"]
    workspace = repo.workspaces[payload["workspace_id"]]
    media = repo.get_media_record(payload["media_id"])
    repo.update_media_status(media["id"], "transcribing")
    is_site_media = False
    with open_site_store_if_available(repo) as store:
        if store is not None:
            site_task = store.get_task_by_media_id(media["id"])
            if site_task is not None:
                is_site_media = True
                store.update_task_status(site_task["id"], "transcribing")
    asr_client = StepFunASRClient.from_env()
    filename = media["stored_name"]
    content_type = media["content_type"]
    download_url = build_authorized_download_url(media["object_name"])
    if getattr(asr_client.config, "show_utterances", False) and is_stepfun_file_audio(
        filename,
        content_type,
    ):
        result = asr_client.transcribe_file_url(download_url, content_type=content_type)
    else:
        data = request_bytes(Request(download_url, method="GET"), asr_client.config.timeout_seconds)
        if is_stepfun_remuxable_audio(filename, content_type):
            data = remux_webm_to_ogg(data)
            filename = f"{Path(filename).stem}.ogg"
            content_type = "audio/ogg"
        result = asr_client.transcribe_bytes(data=data, filename=filename, content_type=content_type)
    task_id = result.get("task_id") or result.get("session_id")
    raw_asr_result = result.get("raw_result") or result
    media_utterances = build_editable_utterances(raw_result=raw_asr_result, transcript_text=result["text"])
    repo.update_media_status(
        media["id"],
        "transcribed",
        asr_task_id=task_id,
        transcript_text=result["text"],
        utterances=media_utterances,
        raw_asr_result=raw_asr_result,
    )
    with open_site_store_if_available(repo) as store:
        if store is not None:
            updated_site_task = store.update_task_status_by_media_id(
                media["id"],
                "completed",
                transcript_text=result["text"],
                raw_result=raw_asr_result,
            )
            is_site_media = is_site_media or updated_site_task is not None
            if updated_site_task is not None:
                try:
                    store.enqueue_task_notification(updated_site_task["id"])
                except Exception:
                    LOGGER.warning(
                        "Could not enqueue completion subscription for task %s; "
                        "the recovery scan will retry.",
                        updated_site_task["id"],
                        exc_info=True,
                    )
    if is_site_media:
        repo.update_media_status(media["id"], "processed")
        repo.complete_job(job["id"], media["id"])
        return
    profile = load_profile(workspace.profile)
    digest = process_record(
        repo=repo,
        workspace_id=payload["workspace_id"],
        profile=profile,
        title=payload["title"],
        text=result["text"],
        extractor=build_extractor(bool(payload.get("use_llm"))),
        digest_renderer=build_digest_renderer(bool(payload.get("use_llm"))),
    )
    repo.update_media_status(media["id"], "processed", record_id=digest.record_id)
    repo.complete_job(job["id"], digest.record_id)


def process_cleanup_expired_media_job(repo: object, job: dict) -> None:
    cleaned = 0
    with open_site_store_if_available(repo) as store:
        if store is None:
            repo.complete_job(job["id"], "cleanup_not_supported")
            return
        for item in store.list_expired_tasks():
            remove_local_file_if_exists(item.get("local_file_path"))
            if item.get("object_name"):
                delete_media_from_b2(item["object_name"])
            store.expire_task(item["task_id"], item.get("media_id"))
            cleaned += 1
    repo.complete_job(job["id"], f"cleanup_{cleaned}")


def compressed_filename(filename: str) -> str:
    return f"{Path(filename).stem}.compressed.ogg"


def upload_media_to_b2_with_retry(
    data: bytes,
    source_name: str,
    content_type: str | None,
    attempts: int = 3,
) -> dict:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return upload_media_to_b2(
                data=data,
                source_name=source_name,
                content_type=content_type,
            )
        except (B2UploadError, URLError, TimeoutError, ssl.SSLError, RemoteDisconnected) as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(1.0 * (attempt + 1))
                continue
            break
    assert last_error is not None
    raise last_error


def compress_audio_for_asr(data: bytes, filename: str, content_type: str | None) -> bytes:
    if is_stepfun_remuxable_audio(filename, content_type):
        return remux_webm_to_ogg(data)
    return transcode_audio_to_ogg_opus(data, filename)


def transcode_audio_to_ogg_opus(data: bytes, filename: str) -> bytes:
    suffix = Path(filename).suffix or ".bin"
    with tempfile.TemporaryDirectory(prefix="recordflow-compress-") as tmpdir:
        input_path = Path(tmpdir) / f"input{suffix}"
        output_path = Path(tmpdir) / "output.ogg"
        input_path.write_bytes(data)
        process = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(input_path),
                "-vn",
                "-ac",
                "1",
                "-c:a",
                "libopus",
                "-b:a",
                "24k",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            error = (process.stderr or process.stdout or "").strip()
            raise RuntimeError(f"ffmpeg audio compression to OGG/Opus failed: {error}")
        output = output_path.read_bytes()
        if not output:
            raise RuntimeError("ffmpeg audio compression to OGG/Opus produced an empty file.")
        return output


def remux_webm_to_ogg(data: bytes) -> bytes:
    with tempfile.TemporaryDirectory(prefix="recordflow-remux-") as tmpdir:
        input_path = Path(tmpdir) / "input.webm"
        output_path = Path(tmpdir) / "output.ogg"
        input_path.write_bytes(data)
        process = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(input_path),
                "-vn",
                "-c:a",
                "copy",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            error = (process.stderr or process.stdout or "").strip()
            raise RuntimeError(f"ffmpeg remux from WebM/Opus to OGG/Opus failed: {error}")
        output = output_path.read_bytes()
        if not output:
            raise RuntimeError("ffmpeg remux from WebM/Opus to OGG/Opus produced an empty file.")
        return output


def run_worker(
    repo: object,
    once: bool = False,
    poll_seconds: float = 1.0,
    max_poll_seconds: float = 4.0,
    job_types: set[str] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> None:
    if hasattr(repo, "requeue_stale_running_jobs"):
        repo.requeue_stale_running_jobs()
    recover_pending_site_notifications(repo)
    last_queue_maintenance = time.monotonic()
    sleep_fn = sleep or time.sleep
    initial_poll_seconds = max(0.0, poll_seconds)
    maximum_poll_seconds = max(initial_poll_seconds, max_poll_seconds)
    idle_poll_seconds = initial_poll_seconds
    while True:
        now = time.monotonic()
        if now - last_queue_maintenance >= QUEUE_MAINTENANCE_INTERVAL_SECONDS:
            if hasattr(repo, "requeue_stale_running_jobs"):
                repo.requeue_stale_running_jobs()
            recover_pending_site_notifications(repo)
            last_queue_maintenance = now
        processed = process_next_job(repo, job_types=job_types)
        if once:
            return
        if processed:
            idle_poll_seconds = initial_poll_seconds
            continue
        sleep_fn(idle_poll_seconds)
        idle_poll_seconds = min(
            maximum_poll_seconds,
            max(initial_poll_seconds, idle_poll_seconds * 2.0),
        )


def recover_pending_site_notifications(repo: object) -> int:
    try:
        with open_site_store_if_available(repo) as store:
            if store is None:
                return 0
            return len(store.enqueue_pending_task_notifications())
    except Exception:
        LOGGER.warning("Could not recover pending completion subscriptions.", exc_info=True)
        return 0


class _NullContext:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return False


class _StoreContext:
    def __init__(self, store: ASRSiteStore) -> None:
        self.store = store

    def __enter__(self) -> ASRSiteStore:
        return self.store

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.store.close()
        return False


def open_site_store_if_available(repo: object):
    try:
        return _StoreContext(ASRSiteStore(repo))
    except Exception:
        return _NullContext()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RecordFlow background worker.")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Use a SQLite database path. Ignored when omitted and DATABASE_URL is set.",
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=1.0,
        help="Initial delay between empty queue polls.",
    )
    parser.add_argument(
        "--max-poll-seconds",
        type=float,
        default=4.0,
        help="Maximum delay after repeated empty queue polls.",
    )
    parser.add_argument(
        "--types",
        default="",
        help="Comma-separated job types to process, for example compress_media or transcribe_media,process_record.",
    )
    args = parser.parse_args()
    job_types = {item.strip() for item in args.types.split(",") if item.strip()} or None

    repo = SQLiteRepository(args.db_path) if args.db_path else create_repository()
    try:
        run_worker(
            repo=repo,
            once=args.once,
            poll_seconds=args.poll_seconds,
            max_poll_seconds=args.max_poll_seconds,
            job_types=job_types,
        )
    finally:
        repo.close()


if __name__ == "__main__":
    main()
