from __future__ import annotations

from dataclasses import asdict
import argparse
import ssl
import time
from http.client import RemoteDisconnected
from pathlib import Path
from typing import Any
from urllib.error import URLError

from recordflow_agent.llm_client import load_dotenv
from recordflow_agent.media_storage import B2UploadError, upload_media_to_b2
from recordflow_agent.repository_factory import create_repository
from recordflow_agent.worker import process_next_job


def load_eval_dataset(
    repo: object,
    eval_root: Path,
    *,
    workspace_name: str = "data/eval 在线导入",
    profile_name: str = "detailed_summary",
    use_llm: bool = True,
    reset: bool = True,
) -> dict[str, Any]:
    load_dotenv()
    if reset and hasattr(repo, "clear_all"):
        repo.clear_all()
    workspace_id = repo.create_workspace(workspace_name, profile_name)
    media_items: list[dict[str, Any]] = []
    for path in discover_audio_files(eval_root):
        data = path.read_bytes()
        upload = upload_media_with_retry(
            data=data,
            source_name=path.name,
            content_type=content_type_for_path(path),
        )
        media_id = repo.add_media_record(
            workspace_id=workspace_id,
            source_name=path.name,
            stored_name=path.name,
            url=upload["url"],
            public_url=upload["public_url"],
            object_name=upload["object_name"],
            content_type=upload["content_type"],
            original_size_bytes=len(data),
            compressed_size_bytes=len(data),
            compression_codec=None,
        )
        job_id = repo.enqueue_media_compression_job(
            workspace_id=workspace_id,
            media_id=media_id,
            title=path.stem,
            use_llm=use_llm,
        )
        media_items.append(
            {
                "path": str(path),
                "media_id": media_id,
                "job_id": job_id,
                "source_name": path.name,
            }
        )

    processed_jobs = 0
    while process_next_job(repo):
        processed_jobs += 1

    return {
        "workspace_id": workspace_id,
        "workspace_name": workspace_name,
        "profile_name": profile_name,
        "media_items": media_items,
        "processed_jobs": processed_jobs,
        "records": to_jsonable(repo.list_records(workspace_id)) if hasattr(repo, "list_records") else [],
        "media": to_jsonable(repo.list_media_records(workspace_id)) if hasattr(repo, "list_media_records") else [],
    }


def discover_audio_files(eval_root: Path) -> list[Path]:
    return sorted(
        path
        for path in eval_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".mp3", ".m4a", ".wav", ".webm", ".ogg", ".flac", ".mp4", ".mov"}
    )


def content_type_for_path(path: Path) -> str | None:
    suffix = path.suffix.lower()
    return {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".wav": "audio/wav",
        ".webm": "audio/webm",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
    }.get(suffix)


def upload_media_with_retry(
    *,
    data: bytes,
    source_name: str,
    content_type: str | None,
    attempts: int = 3,
) -> dict[str, Any]:
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


def to_jsonable(value: Any) -> Any:
    if hasattr(value, "__dict__"):
        return asdict(value)
    from recordflow_agent.serialization import to_jsonable as _to_jsonable

    return _to_jsonable(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load data/eval into the configured RecordFlow database.")
    parser.add_argument("--eval-root", default=str(Path(__file__).resolve().parent.parent / "data" / "eval"))
    parser.add_argument("--workspace-name", default="data/eval 在线导入")
    parser.add_argument("--profile", default="detailed_summary")
    parser.add_argument("--use-llm", action="store_true", default=True)
    parser.add_argument("--no-use-llm", dest="use_llm", action="store_false")
    parser.add_argument("--reset", dest="reset", action="store_true", default=True)
    parser.add_argument("--no-reset", dest="reset", action="store_false")
    args = parser.parse_args()
    repo = create_repository()
    result = load_eval_dataset(
        repo,
        Path(args.eval_root),
        workspace_name=args.workspace_name,
        profile_name=args.profile,
        use_llm=args.use_llm,
        reset=args.reset,
    )
    print(result)


if __name__ == "__main__":
    main()
