from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import ssl
import time
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


COMPRESSED_AUDIO_MIME_TYPES = {
    "audio/aac",
    "audio/mp4",
    "audio/mpeg",
    "audio/mp3",
    "audio/ogg",
    "audio/opus",
    "audio/webm",
    "video/webm",
}
COMPRESSED_AUDIO_EXTENSIONS = {".aac", ".m4a", ".mp3", ".ogg", ".opus", ".webm", ".wav"}
SUPPORTED_UPLOAD_MIME_TYPES = {
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
    "audio/x-wav",
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "video/x-m4v",
}
SUPPORTED_UPLOAD_EXTENSIONS = {
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
UNCOMPRESSED_AUDIO_MIME_TYPES = {
    "audio/aiff",
    "audio/flac",
    "audio/x-aiff",
}
UNCOMPRESSED_AUDIO_EXTENSIONS = {".aif", ".aiff", ".flac", ".pcm"}


@dataclass(frozen=True)
class B2Settings:
    key_id: str
    application_key: str
    bucket_name: str
    bucket_id: str | None
    public_base_url: str
    cdn_base_url: str | None = None

    @classmethod
    def from_env(cls) -> "B2Settings":
        key_id = os.getenv("RECORDFLOW_B2_KEY_ID", "").strip()
        application_key = os.getenv("RECORDFLOW_B2_APPLICATION_KEY", "").strip()
        bucket_name = os.getenv("RECORDFLOW_B2_BUCKET_NAME", "").strip()
        bucket_id = os.getenv("RECORDFLOW_B2_BUCKET_ID", "").strip()
        public_base_url = os.getenv("RECORDFLOW_B2_PUBLIC_BASE_URL", "").strip()
        cdn_base_url = os.getenv("RECORDFLOW_B2_CDN_BASE_URL", "").strip() or None
        missing = [
            name
            for name, value in [
                ("RECORDFLOW_B2_KEY_ID", key_id),
                ("RECORDFLOW_B2_APPLICATION_KEY", application_key),
                ("RECORDFLOW_B2_BUCKET_NAME", bucket_name),
            ]
            if not value
        ]
        if missing:
            raise B2ConfigurationError(
                "Backblaze B2 is not configured. Missing: " + ", ".join(missing)
            )
        if not public_base_url:
            public_base_url = f"https://f005.backblazeb2.com/file/{bucket_name}"
        return cls(
            key_id=key_id,
            application_key=application_key,
            bucket_name=bucket_name,
            bucket_id=bucket_id,
            public_base_url=public_base_url.rstrip("/"),
            cdn_base_url=cdn_base_url.rstrip("/") if cdn_base_url else None,
        )


@dataclass(frozen=True)
class FileStorageSettings:
    root: Path
    public_base_url: str

    @classmethod
    def from_env(cls) -> "FileStorageSettings":
        root = Path(os.getenv("RECORDFLOW_FS_STORAGE_ROOT", "").strip() or "/record")
        public_base_url = os.getenv("RECORDFLOW_FS_PUBLIC_BASE_URL", "").strip()
        if not public_base_url:
            raise B2ConfigurationError(
                "Filesystem media storage is not configured. Missing: "
                "RECORDFLOW_FS_PUBLIC_BASE_URL"
            )
        return cls(root=root, public_base_url=public_base_url.rstrip("/"))


class B2ConfigurationError(RuntimeError):
    pass


class B2UploadError(RuntimeError):
    pass


def is_supported_client_compressed_audio(filename: str, content_type: str | None) -> bool:
    suffix = PurePosixPath(filename.lower()).suffix
    mime_type = normalize_mime_type(content_type)
    if mime_type in UNCOMPRESSED_AUDIO_MIME_TYPES or suffix in UNCOMPRESSED_AUDIO_EXTENSIONS:
        return False
    return mime_type in COMPRESSED_AUDIO_MIME_TYPES or suffix in COMPRESSED_AUDIO_EXTENSIONS


def is_supported_upload_media(filename: str, content_type: str | None) -> bool:
    suffix = PurePosixPath(filename.lower()).suffix
    mime_type = normalize_mime_type(content_type)
    return mime_type in SUPPORTED_UPLOAD_MIME_TYPES or suffix in SUPPORTED_UPLOAD_EXTENSIONS


def guess_upload_content_type(filename: str, content_type: str | None) -> str:
    mime_type = normalize_mime_type(content_type)
    if mime_type and mime_type != "application/octet-stream":
        return mime_type
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def build_media_object_name(source_name: str, content_type: str | None) -> str:
    safe_name = sanitize_filename(source_name)
    suffix = PurePosixPath(safe_name.lower()).suffix
    if not suffix:
        suffix = extension_for_content_type(content_type)
        safe_name = f"{safe_name}{suffix}"
    date_path = time.strftime("%Y/%m/%d")
    timestamp = int(time.time() * 1000)
    digest = hashlib.sha1(f"{safe_name}:{timestamp}".encode("utf-8")).hexdigest()[:10]
    return f"uploads/{date_path}/{timestamp}-{digest}-{safe_name}"


def configured_storage_backend() -> str:
    backend = os.getenv("RECORDFLOW_MEDIA_STORAGE_BACKEND", "b2").strip().lower()
    if backend in {"filesystem", "fs", "local", "mounted", "oss"}:
        return "filesystem"
    return "b2"


def sanitize_filename(filename: str) -> str:
    name = PurePosixPath(filename or "recording").name.strip()
    if not name:
        name = "recording"
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name)
    name = name.strip(".-") or "recording"
    return name[:120]


def extension_for_content_type(content_type: str | None) -> str:
    mime_type = normalize_mime_type(content_type)
    return {
        "audio/aac": ".aac",
        "audio/mp4": ".m4a",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/ogg": ".ogg",
        "audio/opus": ".opus",
        "audio/webm": ".webm",
        "video/webm": ".webm",
        "audio/wav": ".wav",
        "audio/wave": ".wav",
        "audio/x-wav": ".wav",
    }.get(mime_type, ".bin")


def normalize_mime_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def upload_media_to_b2(
    data: bytes,
    source_name: str,
    content_type: str | None,
    settings: B2Settings | None = None,
) -> dict[str, Any]:
    if settings is None and configured_storage_backend() == "filesystem":
        return upload_media_to_filesystem(data=data, source_name=source_name, content_type=content_type)

    settings = settings or B2Settings.from_env()
    object_name = build_media_object_name(source_name, content_type)
    upload_content_type = guess_upload_content_type(object_name, content_type)
    auth = authorize_account(settings)
    bucket_id = settings.bucket_id or find_bucket_id(auth, settings.bucket_name)
    upload = get_upload_url(auth, bucket_id)
    sha1 = hashlib.sha1(data).hexdigest()
    request = Request(
        upload["uploadUrl"],
        data=data,
        method="POST",
        headers={
            "Authorization": upload["authorizationToken"],
            "X-Bz-File-Name": quote(object_name, safe="/"),
            "Content-Type": upload_content_type,
            "Content-Length": str(len(data)),
            "X-Bz-Content-Sha1": sha1,
        },
    )
    try:
        response = request_json(request)
    except HTTPError as exc:
        raise B2UploadError(f"Backblaze B2 upload failed with HTTP {exc.code}.") from exc
    public_url = f"{settings.public_base_url}/{quote(object_name, safe='/')}"
    cdn_url = (
        f"{settings.cdn_base_url}/{quote(object_name, safe='/')}"
        if settings.cdn_base_url
        else public_url
    )
    return {
        "bucket": settings.bucket_name,
        "object_name": object_name,
        "file_id": response.get("fileId"),
        "content_type": upload_content_type,
        "size_bytes": len(data),
        "sha1": sha1,
        "url": cdn_url,
        "public_url": public_url,
    }


def upload_media_to_filesystem(
    data: bytes,
    source_name: str,
    content_type: str | None,
    settings: FileStorageSettings | None = None,
) -> dict[str, Any]:
    settings = settings or FileStorageSettings.from_env()
    object_name = build_media_object_name(source_name, content_type)
    target_path = safe_storage_path(settings.root, object_name)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(data)
    upload_content_type = guess_upload_content_type(object_name, content_type)
    sha1 = hashlib.sha1(data).hexdigest()
    public_url = f"{settings.public_base_url}/{quote(object_name, safe='/')}"
    return {
        "bucket": "filesystem",
        "object_name": object_name,
        "file_id": None,
        "content_type": upload_content_type,
        "size_bytes": len(data),
        "sha1": sha1,
        "url": public_url,
        "public_url": public_url,
    }


def safe_storage_path(root: Path, object_name: str) -> Path:
    root = root.resolve()
    relative = PurePosixPath(object_name)
    if relative.is_absolute() or ".." in relative.parts:
        raise B2UploadError("Invalid media object name.")
    target = (root / Path(*relative.parts)).resolve()
    if target != root and root not in target.parents:
        raise B2UploadError("Invalid media object path.")
    return target


def authorize_account(settings: B2Settings) -> dict[str, Any]:
    token = base64.b64encode(
        f"{settings.key_id}:{settings.application_key}".encode("utf-8")
    ).decode("ascii")
    request = Request(
        "https://api.backblazeb2.com/b2api/v3/b2_authorize_account",
        method="GET",
        headers={"Authorization": f"Basic {token}"},
    )
    try:
        return request_json(request)
    except HTTPError as exc:
        raise B2UploadError(f"Backblaze B2 authorization failed with HTTP {exc.code}.") from exc


def get_upload_url(auth: dict[str, Any], bucket_id: str) -> dict[str, Any]:
    api_url = auth["apiInfo"]["storageApi"]["apiUrl"].rstrip("/")
    token = auth["authorizationToken"]
    request = Request(
        f"{api_url}/b2api/v3/b2_get_upload_url",
        data=json.dumps({"bucketId": bucket_id}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": token,
            "Content-Type": "application/json",
        },
    )
    try:
        return request_json(request)
    except HTTPError as exc:
        raise B2UploadError(f"Backblaze B2 upload URL request failed with HTTP {exc.code}.") from exc


def find_bucket_id(auth: dict[str, Any], bucket_name: str) -> str:
    api_url = auth["apiInfo"]["storageApi"]["apiUrl"].rstrip("/")
    account_id = auth["accountId"]
    token = auth["authorizationToken"]
    request = Request(
        f"{api_url}/b2api/v3/b2_list_buckets",
        data=json.dumps({"accountId": account_id, "bucketName": bucket_name}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": token,
            "Content-Type": "application/json",
        },
    )
    try:
        response = request_json(request)
    except HTTPError as exc:
        raise B2UploadError(f"Backblaze B2 bucket lookup failed with HTTP {exc.code}.") from exc
    buckets = response.get("buckets", [])
    if not buckets:
        raise B2UploadError(f"Backblaze B2 bucket was not found: {bucket_name}.")
    return buckets[0]["bucketId"]


def build_authorized_download_url(
    object_name: str,
    settings: B2Settings | None = None,
    valid_duration_seconds: int = 3600,
) -> str:
    if settings is None and configured_storage_backend() == "filesystem":
        file_settings = FileStorageSettings.from_env()
        return f"{file_settings.public_base_url}/{quote(object_name, safe='/')}"

    settings = settings or B2Settings.from_env()
    auth = authorize_account(settings)
    bucket_id = settings.bucket_id or find_bucket_id(auth, settings.bucket_name)
    token = get_download_authorization(
        auth=auth,
        bucket_id=bucket_id,
        file_name_prefix=object_name,
        valid_duration_seconds=valid_duration_seconds,
    )
    public_url = f"{settings.public_base_url}/{quote(object_name, safe='/')}"
    return f"{public_url}?{urlencode({'Authorization': token})}"


def delete_media_from_b2(
    object_name: str,
    settings: B2Settings | None = None,
) -> None:
    if settings is None and configured_storage_backend() == "filesystem":
        target_path = safe_storage_path(FileStorageSettings.from_env().root, object_name)
        try:
            target_path.unlink()
        except FileNotFoundError:
            pass
        return

    settings = settings or B2Settings.from_env()
    auth = authorize_account(settings)
    file_info = find_file_version_by_name(auth, settings.bucket_name, object_name)
    if file_info is None:
        return
    api_url = auth["apiInfo"]["storageApi"]["apiUrl"].rstrip("/")
    request = Request(
        f"{api_url}/b2api/v3/b2_delete_file_version",
        data=json.dumps(
            {
                "fileName": file_info["fileName"],
                "fileId": file_info["fileId"],
            }
        ).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": auth["authorizationToken"],
            "Content-Type": "application/json",
        },
    )
    try:
        request_json(request)
    except HTTPError as exc:
        raise B2UploadError(f"Backblaze B2 delete failed with HTTP {exc.code}.") from exc


def get_download_authorization(
    auth: dict[str, Any],
    bucket_id: str,
    file_name_prefix: str,
    valid_duration_seconds: int,
) -> str:
    api_url = auth["apiInfo"]["storageApi"]["apiUrl"].rstrip("/")
    request = Request(
        f"{api_url}/b2api/v3/b2_get_download_authorization",
        data=json.dumps(
            {
                "bucketId": bucket_id,
                "fileNamePrefix": file_name_prefix,
                "validDurationInSeconds": valid_duration_seconds,
            }
        ).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": auth["authorizationToken"],
            "Content-Type": "application/json",
        },
    )
    try:
        response = request_json(request)
    except HTTPError as exc:
        raise B2UploadError(
            f"Backblaze B2 download authorization failed with HTTP {exc.code}."
        ) from exc
    token = response.get("authorizationToken")
    if not token:
        raise B2UploadError("Backblaze B2 did not return a download authorization token.")
    return token


def find_file_version_by_name(
    auth: dict[str, Any],
    bucket_name: str,
    object_name: str,
) -> dict[str, Any] | None:
    api_url = auth["apiInfo"]["storageApi"]["apiUrl"].rstrip("/")
    account_id = auth["accountId"]
    request = Request(
        f"{api_url}/b2api/v3/b2_list_file_names",
        data=json.dumps(
            {
                "accountId": account_id,
                "bucketId": find_bucket_id(auth, bucket_name),
                "prefix": object_name,
                "maxFileCount": 1,
            }
        ).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": auth["authorizationToken"],
            "Content-Type": "application/json",
        },
    )
    try:
        response = request_json(request)
    except HTTPError as exc:
        raise B2UploadError(f"Backblaze B2 file lookup failed with HTTP {exc.code}.") from exc
    files = response.get("files") or []
    if not files:
        return None
    file_info = files[0]
    if file_info.get("fileName") != object_name:
        return None
    return file_info


def request_json(request: Request, attempts: int = 3) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError:
            raise
        except (URLError, TimeoutError, ssl.SSLError) as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
            break
    raise B2UploadError(f"Backblaze B2 network error: {last_error}") from last_error
