from fastapi.testclient import TestClient

from recordflow_agent import api
from recordflow_agent.api import create_app
from recordflow_agent.media_storage import B2UploadError
from recordflow_agent.sqlite_repository import SQLiteRepository


def test_media_upload_requires_b2_configuration(tmp_path, monkeypatch):
    for key in [
        "RECORDFLOW_B2_KEY_ID",
        "RECORDFLOW_B2_APPLICATION_KEY",
        "RECORDFLOW_B2_BUCKET_NAME",
    ]:
        monkeypatch.setenv(key, "")
    app = create_app(SQLiteRepository(tmp_path / "recordflow.db"))
    client = TestClient(app)

    response = client.post(
        "/media/uploads",
        files={"file": ("meeting.webm", b"audio-bytes", "audio/webm")},
        data={"source_name": "meeting.wav"},
    )

    assert response.status_code == 503
    assert "Backblaze B2 is not configured" in response.json()["detail"]


def test_media_upload_accepts_uncompressed_audio_for_backend_compression(tmp_path, monkeypatch):
    monkeypatch.setenv("RECORDFLOW_B2_KEY_ID", "key-id")
    monkeypatch.setenv("RECORDFLOW_B2_APPLICATION_KEY", "application-key")
    monkeypatch.setenv("RECORDFLOW_B2_BUCKET_NAME", "record-flow")
    app = create_app(SQLiteRepository(tmp_path / "recordflow.db"))
    client = TestClient(app)

    def fake_upload_media_to_b2(data, source_name, content_type):
        return {
            "bucket": "record-flow",
            "object_name": "uploads/meeting.flac",
            "file_id": "file-id",
            "content_type": content_type,
            "size_bytes": len(data),
            "sha1": "sha1",
            "url": "https://img.blenet.top/file/record-flow/uploads/meeting.flac",
            "public_url": "https://f005.backblazeb2.com/file/record-flow/uploads/meeting.flac",
        }

    monkeypatch.setattr(api, "upload_media_to_b2", fake_upload_media_to_b2)

    response = client.post(
        "/media/uploads",
        files={"file": ("meeting.flac", b"audio-bytes", "audio/flac")},
        data={"source_name": "meeting.flac"},
    )

    assert response.status_code == 200
    assert response.json()["media"]["client_compressed"] is False


def test_media_upload_persists_media_and_enqueues_compression_job(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)
    workspace_id = client.post(
        "/workspaces",
        json={"name": "RecordFlow product", "profile": "project_meeting"},
    ).json()["id"]

    def fake_upload_media_to_b2(data, source_name, content_type):
        return {
            "bucket": "record-flow",
            "object_name": "uploads/meeting.ogg",
            "file_id": "file-id",
            "content_type": content_type,
            "size_bytes": len(data),
            "sha1": "sha1",
            "url": "https://img.blenet.top/file/record-flow/uploads/meeting.ogg",
            "public_url": "https://f005.backblazeb2.com/file/record-flow/uploads/meeting.ogg",
        }

    monkeypatch.setattr(api, "upload_media_to_b2", fake_upload_media_to_b2)

    response = client.post(
        f"/workspaces/{workspace_id}/media/uploads",
        files={"file": ("meeting.ogg", b"audio-bytes", "audio/ogg")},
        data={
            "source_name": "meeting.wav",
            "original_size_bytes": "1000",
            "compressed_size_bytes": "11",
            "compression_codec": "audio/ogg;codecs=opus",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["media"]["status"] == "uploaded"
    assert body["job"]["type"] == "compress_media"
    assert body["job"]["status"] == "pending"
    saved = repo.get_media_record(body["media"]["id"])
    assert saved["workspace_id"] == workspace_id
    assert saved["url"].startswith("https://img.blenet.top/")
    repo.close()


def test_workspace_media_upload_accepts_webm_opus_for_worker_remux(
    tmp_path,
    monkeypatch,
):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)
    workspace_id = client.post(
        "/workspaces",
        json={"name": "RecordFlow product", "profile": "project_meeting"},
    ).json()["id"]

    def fake_upload_media_to_b2(data, source_name, content_type):
        return {
            "bucket": "record-flow",
            "object_name": "uploads/meeting.webm",
            "file_id": "file-id",
            "content_type": content_type,
            "size_bytes": len(data),
            "sha1": "sha1",
            "url": "https://img.blenet.top/file/record-flow/uploads/meeting.webm",
            "public_url": "https://f005.backblazeb2.com/file/record-flow/uploads/meeting.webm",
        }

    monkeypatch.setattr(api, "upload_media_to_b2", fake_upload_media_to_b2)

    response = client.post(
        f"/workspaces/{workspace_id}/media/uploads",
        files={"file": ("meeting.webm", b"audio-bytes", "audio/webm")},
        data={"source_name": "meeting.wav"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["media"]["stored_name"] == "meeting.webm"
    assert body["media"]["content_type"] == "audio/webm"
    assert body["job"]["type"] == "compress_media"
    repo.close()


def test_workspace_media_upload_accepts_video_for_backend_audio_extraction(
    tmp_path,
    monkeypatch,
):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)
    workspace_id = client.post(
        "/workspaces",
        json={"name": "RecordFlow product", "profile": "project_meeting"},
    ).json()["id"]

    def fake_upload_media_to_b2(data, source_name, content_type):
        return {
            "bucket": "record-flow",
            "object_name": "uploads/demo.mp4",
            "file_id": "file-id",
            "content_type": content_type,
            "size_bytes": len(data),
            "sha1": "sha1",
            "url": "https://img.blenet.top/file/record-flow/uploads/demo.mp4",
            "public_url": "https://f005.backblazeb2.com/file/record-flow/uploads/demo.mp4",
        }

    monkeypatch.setattr(api, "upload_media_to_b2", fake_upload_media_to_b2)

    response = client.post(
        f"/workspaces/{workspace_id}/media/uploads",
        files={"file": ("demo.mp4", b"video-bytes", "video/mp4")},
        data={"source_name": "demo.mp4"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["media"]["stored_name"] == "demo.mp4"
    assert body["media"]["content_type"] == "video/mp4"
    assert body["job"]["type"] == "compress_media"
    repo.close()


def test_workspace_media_upload_accepts_raw_audio_larger_than_stepaudio_sse_limit_for_compression(
    tmp_path,
    monkeypatch,
):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)
    workspace_id = client.post(
        "/workspaces",
        json={"name": "RecordFlow product", "profile": "project_meeting"},
    ).json()["id"]
    called = {"upload": False}

    def fake_upload_media_to_b2(data, source_name, content_type):
        called["upload"] = True
        return {
            "bucket": "record-flow",
            "object_name": "uploads/large.ogg",
            "file_id": "file-id",
            "content_type": content_type,
            "size_bytes": len(data),
            "sha1": "sha1",
            "url": "https://img.blenet.top/file/record-flow/uploads/large.ogg",
            "public_url": "https://f005.backblazeb2.com/file/record-flow/uploads/large.ogg",
        }

    monkeypatch.setattr(api, "upload_media_to_b2", fake_upload_media_to_b2)

    response = client.post(
        f"/workspaces/{workspace_id}/media/uploads",
        files={"file": ("large.ogg", b"audio-bytes", "audio/ogg")},
        data={
            "source_name": "large.ogg",
            "compressed_size_bytes": str(80 * 1024 * 1024),
        },
    )

    assert response.status_code == 200
    assert response.json()["job"]["type"] == "compress_media"
    assert called["upload"] is True
    repo.close()


def test_workspace_media_upload_returns_502_when_b2_network_fails(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)
    workspace_id = client.post(
        "/workspaces",
        json={"name": "RecordFlow product", "profile": "project_meeting"},
    ).json()["id"]

    def fake_upload_media_to_b2(data, source_name, content_type):
        raise B2UploadError("Backblaze B2 network error: temporary ssl eof")

    monkeypatch.setattr(api, "upload_media_to_b2", fake_upload_media_to_b2)

    response = client.post(
        f"/workspaces/{workspace_id}/media/uploads",
        files={"file": ("meeting.ogg", b"audio-bytes", "audio/ogg")},
        data={"source_name": "meeting.wav"},
    )

    assert response.status_code == 502
    assert "Backblaze B2 network error" in response.json()["detail"]
    repo.close()


def test_workspace_media_upload_does_not_reject_long_recordings_by_duration(
    tmp_path,
    monkeypatch,
):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    app = create_app(repo)
    client = TestClient(app)
    workspace_id = client.post(
        "/workspaces",
        json={"name": "RecordFlow product", "profile": "project_meeting"},
    ).json()["id"]
    called = {"upload": False}

    def fake_upload_media_to_b2(data, source_name, content_type):
        called["upload"] = True
        return {
            "bucket": "record-flow",
            "object_name": "uploads/long.ogg",
            "file_id": "file-id",
            "content_type": content_type,
            "size_bytes": len(data),
            "sha1": "sha1",
            "url": "https://img.blenet.top/file/record-flow/uploads/long.ogg",
            "public_url": "https://f005.backblazeb2.com/file/record-flow/uploads/long.ogg",
        }

    monkeypatch.setattr(api, "upload_media_to_b2", fake_upload_media_to_b2)

    response = client.post(
        f"/workspaces/{workspace_id}/media/uploads",
        files={"file": ("long.ogg", b"audio-bytes", "audio/ogg")},
        data={
            "source_name": "long.ogg",
            "duration_seconds": str(15 * 60),
        },
    )

    assert response.status_code == 200
    assert response.json()["job"]["type"] == "compress_media"
    assert called["upload"] is True
    repo.close()
