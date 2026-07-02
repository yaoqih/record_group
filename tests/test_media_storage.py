from recordflow_agent import media_storage
from recordflow_agent.media_storage import (
    B2UploadError,
    B2Settings,
    build_authorized_download_url,
    request_json,
    upload_media_to_b2,
)


def test_upload_media_to_b2_resolves_bucket_id_and_returns_cdn_url(monkeypatch):
    calls = []

    def fake_authorize(settings):
        calls.append(("authorize", settings.bucket_name))
        return {
            "accountId": "account-id",
            "authorizationToken": "account-token",
            "apiInfo": {"storageApi": {"apiUrl": "https://api.example.test"}},
        }

    def fake_find_bucket_id(auth, bucket_name):
        calls.append(("find_bucket_id", bucket_name))
        return "resolved-bucket-id"

    def fake_get_upload_url(auth, bucket_id):
        calls.append(("get_upload_url", bucket_id))
        return {
            "uploadUrl": "https://upload.example.test",
            "authorizationToken": "upload-token",
        }

    def fake_request_json(request):
        calls.append(("upload", request.headers["X-bz-file-name"]))
        return {"fileId": "file-id"}

    monkeypatch.setattr(media_storage, "authorize_account", fake_authorize)
    monkeypatch.setattr(media_storage, "find_bucket_id", fake_find_bucket_id)
    monkeypatch.setattr(media_storage, "get_upload_url", fake_get_upload_url)
    monkeypatch.setattr(media_storage, "request_json", fake_request_json)
    settings = B2Settings(
        key_id="key-id",
        application_key="application-key",
        bucket_name="record-flow",
        bucket_id=None,
        public_base_url="https://f005.backblazeb2.com/file/record-flow",
        cdn_base_url="https://img.blenet.top/file/record-flow",
    )

    result = upload_media_to_b2(
        data=b"audio-bytes",
        source_name="meeting compressed.webm",
        content_type="audio/webm",
        settings=settings,
    )

    assert result["file_id"] == "file-id"
    assert result["bucket"] == "record-flow"
    assert result["content_type"] == "audio/webm"
    assert result["url"].startswith("https://img.blenet.top/file/record-flow/uploads/")
    assert result["public_url"].startswith("https://f005.backblazeb2.com/file/record-flow/uploads/")
    assert ("find_bucket_id", "record-flow") in calls
    assert ("get_upload_url", "resolved-bucket-id") in calls


def test_supported_client_compressed_audio_rejects_wav():
    assert media_storage.is_supported_client_compressed_audio("recording.webm", "audio/webm")
    assert media_storage.is_supported_client_compressed_audio("recording.wav", "audio/wav")
    assert not media_storage.is_supported_client_compressed_audio("recording.flac", "audio/flac")


def test_supported_upload_media_accepts_common_audio_and_video():
    assert media_storage.is_supported_upload_media("recording.flac", "audio/flac")
    assert media_storage.is_supported_upload_media("recording.wav", "audio/wav")
    assert media_storage.is_supported_upload_media("demo.mp4", "video/mp4")
    assert media_storage.is_supported_upload_media("demo.mov", "video/quicktime")
    assert not media_storage.is_supported_upload_media("notes.txt", "text/plain")


def test_build_authorized_download_url_uses_b2_download_authorization(monkeypatch):
    def fake_authorize(settings):
        return {
            "authorizationToken": "account-token",
            "apiInfo": {"storageApi": {"apiUrl": "https://api.example.test"}},
        }

    def fake_request_json(request):
        return {"authorizationToken": "download-token"}

    monkeypatch.setattr(media_storage, "authorize_account", fake_authorize)
    monkeypatch.setattr(media_storage, "request_json", fake_request_json)
    settings = B2Settings(
        key_id="key-id",
        application_key="application-key",
        bucket_name="record-flow",
        bucket_id="bucket-id",
        public_base_url="https://f005.backblazeb2.com/file/record-flow",
        cdn_base_url="https://img.blenet.top/file/record-flow",
    )

    url = build_authorized_download_url(
        object_name="uploads/meeting compressed.wav",
        settings=settings,
        valid_duration_seconds=3600,
    )

    assert url.startswith("https://f005.backblazeb2.com/file/record-flow/uploads/meeting%20compressed.wav")
    assert "Authorization=download-token" in url


def test_request_json_retries_transient_url_errors(monkeypatch):
    attempts = {"count": 0}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(request, timeout):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise media_storage.URLError("temporary ssl eof")
        return FakeResponse()

    monkeypatch.setattr(media_storage, "urlopen", fake_urlopen)
    monkeypatch.setattr(media_storage.time, "sleep", lambda seconds: None)

    result = request_json(object())

    assert result == {"ok": True}
    assert attempts["count"] == 2


def test_request_json_wraps_repeated_url_errors(monkeypatch):
    def fake_urlopen(request, timeout):
        raise media_storage.URLError("temporary ssl eof")

    monkeypatch.setattr(media_storage, "urlopen", fake_urlopen)
    monkeypatch.setattr(media_storage.time, "sleep", lambda seconds: None)

    try:
        request_json(object(), attempts=2)
    except B2UploadError as exc:
        assert "network error" in str(exc)
    else:
        raise AssertionError("request_json should wrap repeated URL errors")
