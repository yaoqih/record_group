import pytest

from recordflow_agent import worker as worker_module
from recordflow_agent.profiles import load_profile
from recordflow_agent.asr_client import STEPFUN_MAX_AUDIO_DATA_BYTES
from recordflow_agent.sqlite_repository import SQLiteRepository
from recordflow_agent.worker import process_next_job, run_worker, transcode_audio_to_ogg_opus


def test_worker_backs_off_when_idle_and_resets_after_processing(monkeypatch):
    poll_results = iter([False, False, False, False, True, False])
    sleep_delays = []

    class WorkerStopped(Exception):
        pass

    monkeypatch.setattr(
        worker_module,
        "process_next_job",
        lambda repo, job_types=None: next(poll_results),
    )

    def fake_sleep(seconds):
        sleep_delays.append(seconds)
        if len(sleep_delays) == 5:
            raise WorkerStopped

    with pytest.raises(WorkerStopped):
        run_worker(
            repo=object(),
            poll_seconds=1.0,
            max_poll_seconds=4.0,
            sleep=fake_sleep,
        )

    assert sleep_delays == [1.0, 2.0, 4.0, 4.0, 1.0]


def test_worker_processes_queued_record_job_and_updates_state(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    job_id = repo.enqueue_record_job(
        workspace_id=workspace_id,
        title="meeting 1",
        text="决定先做文本导入 MVP。张三负责后端，周五前完成。",
        use_llm=False,
    )

    before = repo.get_job(job_id)
    processed = process_next_job(repo)
    after = repo.get_job(job_id)

    assert before["status"] == "pending"
    assert processed is True
    assert after["status"] == "completed"
    assert after["record_id"]
    assert len(repo.list_state_objects(workspace_id)) >= 2
    repo.close()


def test_worker_extracts_basic_state_from_english_meeting_transcript(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    job_id = repo.enqueue_record_job(
        workspace_id=workspace_id,
        title="english meeting",
        text=(
            "We need to make a decision on the remote control concepts. "
            "We decided the target group is people who can afford it. "
            "Our main objectives are simplicity and fashion. "
            "There is a risk that the LCD display will increase cost. "
            "Sarah is responsible for sending the interface notes by Friday."
        ),
        use_llm=False,
    )

    processed = process_next_job(repo)
    job = repo.get_job(job_id)
    objects = repo.list_state_objects(workspace_id)

    assert processed is True
    assert job["status"] == "completed"
    assert len(objects) >= 3
    assert {obj.type.value for obj in objects} >= {"Decision", "Task", "Risk"}
    repo.close()


def test_worker_marks_job_failed_when_workspace_is_missing(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    job_id = repo.enqueue_record_job(
        workspace_id="missing",
        title="bad job",
        text="张三负责后端，周五前完成。",
        use_llm=False,
    )

    processed = process_next_job(repo)
    job = repo.get_job(job_id)

    assert processed is True
    assert job["status"] == "failed"
    assert "missing" in job["error"]
    repo.close()


def test_worker_can_filter_job_types_without_claiming_other_work(tmp_path):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    process_job_id = repo.enqueue_record_job(
        workspace_id=workspace_id,
        title="meeting 1",
        text="张三负责后端，周五前完成。",
        use_llm=False,
    )

    processed = process_next_job(repo, job_types={"compress_media"})
    job = repo.get_job(process_job_id)

    assert processed is False
    assert job["status"] == "pending"
    repo.close()


def test_worker_transcribes_media_job_and_processes_transcript(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    media_id = repo.add_media_record(
        workspace_id=workspace_id,
        source_name="meeting.wav",
        stored_name="meeting.ogg",
        url="https://img.blenet.top/file/record-flow/uploads/meeting.ogg",
        public_url="https://f005.backblazeb2.com/file/record-flow/uploads/meeting.ogg",
        object_name="uploads/meeting.ogg",
        content_type="audio/ogg",
        original_size_bytes=1000,
        compressed_size_bytes=11,
        compression_codec="audio/ogg;codecs=opus",
    )
    job_id = repo.enqueue_media_transcription_job(
        workspace_id=workspace_id,
        media_id=media_id,
        title="meeting audio",
        use_llm=False,
    )

    captured = {}

    class FakeASRClient:
        config = type("Config", (), {"timeout_seconds": 30})()

        def transcribe_bytes(self, data, filename, content_type):
            captured["data"] = data
            captured["filename"] = filename
            captured["content_type"] = content_type
            return {
                "session_id": "sse-session-id",
                "text": "决定先做音频上传 MVP。李四负责 ASR 接入，周五前完成。",
                "utterances": [],
                "raw_result": {
                    "events": [
                        {
                            "type": "transcript.text.done",
                            "text": "决定先做音频上传 MVP。李四负责 ASR 接入，周五前完成。",
                            "meta": {"session_id": "sse-session-id"},
                        }
                    ]
                },
            }

    monkeypatch.setattr("recordflow_agent.worker.StepFunASRClient.from_env", lambda: FakeASRClient())
    monkeypatch.setattr(
        "recordflow_agent.worker.build_authorized_download_url",
        lambda object_name: f"https://download.example.test/{object_name}?Authorization=token",
    )
    monkeypatch.setattr("recordflow_agent.worker.request_bytes", lambda request, timeout_seconds: b"OGG_BYTES")

    processed = process_next_job(repo)
    job = repo.get_job(job_id)
    media = repo.get_media_record(media_id)

    assert processed is True
    assert job["status"] == "completed"
    assert job["record_id"]
    assert media["status"] == "processed"
    assert media["asr_task_id"] == "sse-session-id"
    assert captured["data"] == b"OGG_BYTES"
    assert captured["filename"] == "meeting.ogg"
    assert captured["content_type"] == "audio/ogg"
    assert "决定先做音频上传 MVP" in media["transcript_text"]
    assert len(repo.list_state_objects(workspace_id)) >= 2
    repo.close()


def test_worker_remuxes_webm_opus_before_asr(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    media_id = repo.add_media_record(
        workspace_id=workspace_id,
        source_name="meeting.webm",
        stored_name="meeting.webm",
        url="https://img.blenet.top/file/record-flow/uploads/meeting.webm",
        public_url="https://f005.backblazeb2.com/file/record-flow/uploads/meeting.webm",
        object_name="uploads/meeting.webm",
        content_type="audio/webm",
        original_size_bytes=1000,
        compressed_size_bytes=11,
        compression_codec="audio/webm;codecs=opus",
    )
    job_id = repo.enqueue_media_transcription_job(
        workspace_id=workspace_id,
        media_id=media_id,
        title="meeting audio",
        use_llm=False,
    )

    captured = {}

    class FakeASRClient:
        config = type("Config", (), {"timeout_seconds": 30})()

        def transcribe_bytes(self, data, filename, content_type):
            captured["filename"] = filename
            captured["content_type"] = content_type
            captured["data_prefix"] = data[:4]
            return {
                "session_id": "sse-session-id",
                "text": "remuxed transcript",
                "utterances": [],
                "raw_result": {
                    "events": [
                        {
                            "type": "transcript.text.done",
                            "text": "remuxed transcript",
                            "meta": {"session_id": "sse-session-id"},
                        }
                    ]
                },
            }

    monkeypatch.setattr("recordflow_agent.worker.StepFunASRClient.from_env", lambda: FakeASRClient())
    monkeypatch.setattr(
        "recordflow_agent.worker.build_authorized_download_url",
        lambda object_name: f"https://download.example.test/{object_name}?Authorization=token",
    )
    monkeypatch.setattr("recordflow_agent.worker.request_bytes", lambda request, timeout_seconds: b"WEBM_BYTES")
    monkeypatch.setattr("recordflow_agent.worker.remux_webm_to_ogg", lambda data: b"OGG_BYTES")

    processed = process_next_job(repo)
    job = repo.get_job(job_id)
    media = repo.get_media_record(media_id)

    assert processed is True
    assert job["status"] == "completed"
    assert media["status"] == "processed"
    assert captured["filename"].endswith(".ogg")
    assert captured["content_type"] == "audio/ogg"
    assert captured["data_prefix"] == b"OGG_"
    repo.close()


def test_worker_uses_file_asr_for_utterances_when_enabled(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    media_id = repo.add_media_record(
        workspace_id=workspace_id,
        source_name="meeting.wav",
        stored_name="meeting.ogg",
        url="https://img.blenet.top/file/record-flow/uploads/meeting.ogg",
        public_url="https://f005.backblazeb2.com/file/record-flow/uploads/meeting.ogg",
        object_name="uploads/meeting.ogg",
        content_type="audio/ogg",
        original_size_bytes=1000,
        compressed_size_bytes=11,
        compression_codec="audio/ogg;codecs=opus",
    )
    job_id = repo.enqueue_media_transcription_job(
        workspace_id=workspace_id,
        media_id=media_id,
        title="meeting audio",
        use_llm=False,
    )

    captured = {}

    class FakeASRClient:
        config = type("Config", (), {"timeout_seconds": 30, "show_utterances": True})()

        def transcribe_file_url(self, url, content_type):
            captured["url"] = url
            captured["content_type"] = content_type
            return {
                "task_id": "file-task-id",
                "text": "带时间戳的转写",
                "utterances": [
                    {"text": "带时间戳的转写", "start_time": 0, "end_time": 1000},
                ],
                "raw_result": {
                    "result": [
                        {
                            "text": "带时间戳的转写",
                            "utterances": [
                                {"text": "带时间戳的转写", "start_time": 0, "end_time": 1000},
                            ],
                        }
                    ]
                },
            }

    monkeypatch.setattr("recordflow_agent.worker.StepFunASRClient.from_env", lambda: FakeASRClient())
    monkeypatch.setattr(
        "recordflow_agent.worker.build_authorized_download_url",
        lambda object_name: f"https://download.example.test/{object_name}?Authorization=token",
    )

    processed = process_next_job(repo)
    job = repo.get_job(job_id)
    media = repo.get_media_record(media_id)

    assert processed is True
    assert job["status"] == "completed"
    assert media["status"] == "processed"
    assert media["asr_task_id"] == "file-task-id"
    assert captured["url"] == "https://download.example.test/uploads/meeting.ogg?Authorization=token"
    assert media["utterances"][0]["end_time"] == 1000
    repo.close()


def test_worker_splits_large_file_asr_utterance_before_persisting_media(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    media_id = repo.add_media_record(
        workspace_id=workspace_id,
        source_name="meeting.wav",
        stored_name="meeting.ogg",
        url="https://img.blenet.top/file/record-flow/uploads/meeting.ogg",
        public_url="https://f005.backblazeb2.com/file/record-flow/uploads/meeting.ogg",
        object_name="uploads/meeting.ogg",
        content_type="audio/ogg",
        original_size_bytes=1000,
        compressed_size_bytes=11,
        compression_codec="audio/ogg;codecs=opus",
    )
    job_id = repo.enqueue_media_transcription_job(
        workspace_id=workspace_id,
        media_id=media_id,
        title="meeting audio",
        use_llm=False,
    )
    words = [
        {
            "text": f"会议内容{i}{'，' if i == 7 else '。' if i == 15 else ''}",
            "start_time": i * 500,
            "end_time": (i + 1) * 500,
        }
        for i in range(16)
    ]
    text = "".join(word["text"] for word in words)

    class FakeASRClient:
        config = type("Config", (), {"timeout_seconds": 30, "show_utterances": True})()

        def transcribe_file_url(self, url, content_type):
            return {
                "task_id": "file-task-id",
                "text": text,
                "utterances": [
                    {"text": text, "start_time": 0, "end_time": 8000, "words": words},
                ],
                "raw_result": {
                    "result": [
                        {
                            "text": text,
                            "utterances": [
                                {"text": text, "start_time": 0, "end_time": 8000, "words": words},
                            ],
                        }
                    ]
                },
            }

    monkeypatch.setattr("recordflow_agent.worker.StepFunASRClient.from_env", lambda: FakeASRClient())
    monkeypatch.setattr(
        "recordflow_agent.worker.build_authorized_download_url",
        lambda object_name: f"https://download.example.test/{object_name}?Authorization=token",
    )

    processed = process_next_job(repo)
    job = repo.get_job(job_id)
    media = repo.get_media_record(media_id)

    assert processed is True
    assert job["status"] == "completed"
    assert media["status"] == "processed"
    assert len(media["utterances"]) == 2
    assert media["utterances"][0]["text"].endswith("，")
    assert media["utterances"][1]["text"].endswith("。")
    repo.close()


def test_worker_fails_media_when_file_asr_fails_in_utterance_mode(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    media_id = repo.add_media_record(
        workspace_id=workspace_id,
        source_name="meeting.wav",
        stored_name="meeting.ogg",
        url="https://img.blenet.top/file/record-flow/uploads/meeting.ogg",
        public_url="https://f005.backblazeb2.com/file/record-flow/uploads/meeting.ogg",
        object_name="uploads/meeting.ogg",
        content_type="audio/ogg",
        original_size_bytes=1000,
        compressed_size_bytes=11,
        compression_codec="audio/ogg;codecs=opus",
    )
    job_id = repo.enqueue_media_transcription_job(
        workspace_id=workspace_id,
        media_id=media_id,
        title="meeting audio",
        use_llm=False,
    )

    captured = {"bytes_called": False}

    class FakeASRClient:
        config = type("Config", (), {"timeout_seconds": 30, "show_utterances": True})()

        def transcribe_file_url(self, url, content_type):
            raise RuntimeError("StepFun ASR file task failed for task task-123.")

        def transcribe_bytes(self, data, filename, content_type):
            captured["bytes_called"] = True
            return {
                "session_id": "fallback-session-id",
                "text": "fallback transcript",
                "utterances": [],
                "raw_result": {
                    "events": [
                        {
                            "type": "transcript.text.done",
                            "text": "fallback transcript",
                            "meta": {"session_id": "fallback-session-id"},
                        }
                    ]
                },
            }

    monkeypatch.setattr("recordflow_agent.worker.StepFunASRClient.from_env", lambda: FakeASRClient())
    monkeypatch.setattr(
        "recordflow_agent.worker.build_authorized_download_url",
        lambda object_name: f"https://download.example.test/{object_name}?Authorization=token",
    )
    monkeypatch.setattr("recordflow_agent.worker.request_bytes", lambda request, timeout_seconds: b"OGG_BYTES")

    processed = process_next_job(repo)
    job = repo.get_job(job_id)
    media = repo.get_media_record(media_id)

    assert processed is True
    assert job["status"] == "failed"
    assert media["status"] == "failed"
    assert media["asr_task_id"] is None
    assert "file task failed" in media["error"]
    assert captured["bytes_called"] is False
    repo.close()


def test_worker_compresses_media_then_enqueues_transcription(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    media_id = repo.add_media_record(
        workspace_id=workspace_id,
        source_name="meeting.wav",
        stored_name="meeting.wav",
        url="https://img.blenet.top/file/record-flow/uploads/meeting.wav",
        public_url="https://f005.backblazeb2.com/file/record-flow/uploads/meeting.wav",
        object_name="uploads/meeting.wav",
        content_type="audio/wav",
        original_size_bytes=50_000_000,
        compressed_size_bytes=50_000_000,
        compression_codec="audio/wav",
    )
    job_id = repo.enqueue_media_compression_job(
        workspace_id=workspace_id,
        media_id=media_id,
        title="meeting audio",
        use_llm=False,
    )

    captured = {}

    def fake_upload_media_to_b2(data, source_name, content_type):
        captured["upload"] = {
            "data": data,
            "source_name": source_name,
            "content_type": content_type,
        }
        return {
            "bucket": "record-flow",
            "object_name": "uploads/meeting.compressed.ogg",
            "file_id": "compressed-file-id",
            "content_type": "audio/ogg",
            "size_bytes": len(data),
            "sha1": "sha1",
            "url": "https://img.blenet.top/file/record-flow/uploads/meeting.compressed.ogg",
            "public_url": "https://f005.backblazeb2.com/file/record-flow/uploads/meeting.compressed.ogg",
        }

    monkeypatch.setattr(
        "recordflow_agent.worker.build_authorized_download_url",
        lambda object_name: f"https://download.example.test/{object_name}?Authorization=token",
    )
    monkeypatch.setattr("recordflow_agent.worker.request_bytes", lambda request, timeout_seconds: b"WAV_BYTES")
    monkeypatch.setattr("recordflow_agent.worker.compress_audio_for_asr", lambda data, filename, content_type: b"OGG_BYTES")
    monkeypatch.setattr("recordflow_agent.worker.upload_media_to_b2", fake_upload_media_to_b2)

    processed = process_next_job(repo)
    completed_job = repo.get_job(job_id)
    media = repo.get_media_record(media_id)
    next_job = repo.claim_next_job()

    assert processed is True
    assert completed_job["status"] == "completed"
    assert media["status"] == "compressed"
    assert media["stored_name"] == "meeting.compressed.ogg"
    assert media["object_name"] == "uploads/meeting.compressed.ogg"
    assert media["content_type"] == "audio/ogg"
    assert media["compressed_size_bytes"] == len(b"OGG_BYTES")
    assert media["compression_codec"] == "audio/ogg;codecs=opus"
    assert captured["upload"]["source_name"] == "meeting.compressed.ogg"
    assert captured["upload"]["content_type"] == "audio/ogg"
    assert next_job is not None
    assert next_job["type"] == "transcribe_media"
    assert next_job["payload"]["media_id"] == media_id
    assert next_job["payload"]["title"] == "meeting audio"
    repo.close()


def test_worker_fails_media_when_backend_compression_still_exceeds_sse_limit(
    tmp_path,
    monkeypatch,
):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    media_id = repo.add_media_record(
        workspace_id=workspace_id,
        source_name="meeting.wav",
        stored_name="meeting.wav",
        url="https://img.blenet.top/file/record-flow/uploads/meeting.wav",
        public_url="https://f005.backblazeb2.com/file/record-flow/uploads/meeting.wav",
        object_name="uploads/meeting.wav",
        content_type="audio/wav",
        original_size_bytes=500_000_000,
        compressed_size_bytes=500_000_000,
        compression_codec=None,
    )
    job_id = repo.enqueue_media_compression_job(
        workspace_id=workspace_id,
        media_id=media_id,
        title="meeting audio",
        use_llm=False,
    )

    called = {"upload": False}

    monkeypatch.setattr(
        "recordflow_agent.worker.build_authorized_download_url",
        lambda object_name: f"https://download.example.test/{object_name}?Authorization=token",
    )
    monkeypatch.setattr("recordflow_agent.worker.request_bytes", lambda request, timeout_seconds: b"WAV_BYTES")
    monkeypatch.setattr(
        "recordflow_agent.worker.compress_audio_for_asr",
        lambda data, filename, content_type: b"x" * (STEPFUN_MAX_AUDIO_DATA_BYTES + 1),
    )
    monkeypatch.setattr(
        "recordflow_agent.worker.upload_media_to_b2",
        lambda *args, **kwargs: called.__setitem__("upload", True),
    )

    processed = process_next_job(repo)
    job = repo.get_job(job_id)
    media = repo.get_media_record(media_id)
    next_job = repo.claim_next_job()

    assert processed is True
    assert job["status"] == "failed"
    assert media["status"] == "failed"
    assert "StepAudio 2.5 ASR SSE audio.data limit is 40MiB" in media["error"]
    assert called["upload"] is False
    assert next_job is None
    repo.close()


def test_worker_transcodes_wav_bytes_to_ogg_opus(tmp_path):
    source = tmp_path / "tone.wav"
    import subprocess

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.25",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(source),
        ],
        check=True,
    )

    output = transcode_audio_to_ogg_opus(source.read_bytes(), "tone.wav")

    assert output[:4] == b"OggS"
    assert len(output) < source.stat().st_size


def test_worker_marks_media_failed_when_sse_transcription_times_out(
    tmp_path,
    monkeypatch,
):
    repo = SQLiteRepository(tmp_path / "recordflow.db")
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    media_id = repo.add_media_record(
        workspace_id=workspace_id,
        source_name="meeting.wav",
        stored_name="meeting.wav",
        url="https://img.blenet.top/file/record-flow/uploads/meeting.wav",
        public_url="https://f005.backblazeb2.com/file/record-flow/uploads/meeting.wav",
        object_name="uploads/meeting.wav",
        content_type="audio/wav",
        original_size_bytes=1000,
        compressed_size_bytes=11,
        compression_codec="audio/wav",
    )
    job_id = repo.enqueue_media_transcription_job(
        workspace_id=workspace_id,
        media_id=media_id,
        title="meeting audio",
        use_llm=False,
    )

    class FakeASRClient:
        config = type("Config", (), {"timeout_seconds": 30})()

        def transcribe_bytes(self, data, filename, content_type):
            raise TimeoutError("StepFun ASR SSE request timed out.")

    monkeypatch.setattr("recordflow_agent.worker.StepFunASRClient.from_env", lambda: FakeASRClient())
    monkeypatch.setattr(
        "recordflow_agent.worker.build_authorized_download_url",
        lambda object_name: f"https://download.example.test/{object_name}?Authorization=token",
    )
    monkeypatch.setattr("recordflow_agent.worker.request_bytes", lambda request, timeout_seconds: b"WAV_BYTES")

    processed = process_next_job(repo)
    job = repo.get_job(job_id)
    media = repo.get_media_record(media_id)

    assert processed is True
    assert job["status"] == "failed"
    assert media["status"] == "failed"
    assert media["asr_task_id"] is None
    assert "SSE request timed out" in media["error"]
    repo.close()
