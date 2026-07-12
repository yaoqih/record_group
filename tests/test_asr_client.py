import json
from urllib.error import HTTPError, URLError

import pytest

from recordflow_agent import asr_client
from recordflow_agent.asr_client import (
    STEPFUN_MAX_AUDIO_DATA_BYTES,
    StepFunASRClient,
    StepFunASRConfig,
)


def test_stepfun_asr_client_posts_audio_bytes_to_sse_and_returns_done_text(monkeypatch):
    requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            return iter(
                [
                    b'data: {"type":"transcript.text.delta","delta":"hello "}\n',
                    b"\n",
                    b'data: {"type":"transcript.text.done","text":"hello world","usage":{"total_tokens":8}}\n',
                    b"\n",
                ]
            )

    def fake_urlopen(request, timeout):
        requests.append(
            {
                "url": request.full_url,
                "headers": dict(request.header_items()),
                "payload": json.loads(request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        return FakeResponse()

    monkeypatch.setattr(asr_client, "urlopen", fake_urlopen)
    client = StepFunASRClient(
        StepFunASRConfig(
            api_key="step-key",
            base_url="https://api.stepfun.com",
            model_name="stepaudio-2.5-asr",
            timeout_seconds=30,
        )
    )

    result = client.transcribe_bytes(
        b"audio-bytes",
        filename="meeting.ogg",
        content_type="audio/ogg",
    )

    assert result["text"] == "hello world"
    assert result["events"][0]["delta"] == "hello "
    assert result["raw_result"]["type"] == "transcript.text.done"
    assert requests[0]["url"] == "https://api.stepfun.com/v1/audio/asr/sse"
    assert requests[0]["headers"]["Authorization"] == "Bearer step-key"
    assert requests[0]["headers"]["Accept"] == "text/event-stream"
    assert requests[0]["payload"]["audio"]["data"] == "YXVkaW8tYnl0ZXM="
    assert requests[0]["payload"]["audio"]["input"]["format"]["type"] == "ogg"
    assert requests[0]["payload"]["audio"]["input"]["transcription"]["model"] == "stepaudio-2.5-asr"
    assert requests[0]["payload"]["audio"]["input"]["transcription"]["enable_itn"] is True


def test_stepfun_asr_client_uses_delta_text_when_done_event_has_no_text(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            return iter(
                [
                    b'data: {"type":"transcript.text.delta","delta":"part one"}\n\n',
                    b'data: {"type":"transcript.text.delta","delta":" part two"}\n\n',
                    b'data: {"type":"transcript.text.done","usage":{"total_tokens":8}}\n\n',
                ]
            )

    monkeypatch.setattr(asr_client, "urlopen", lambda request, timeout: FakeResponse())
    client = StepFunASRClient(StepFunASRConfig(api_key="step-key"))

    result = client.transcribe_bytes(b"audio-bytes", filename="meeting.wav", content_type="audio/wav")

    assert result["text"] == "part one part two"


def test_stepfun_asr_client_raises_when_sse_emits_error(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            return iter([b'data: {"type":"error","message":"bad audio"}\n\n'])

    monkeypatch.setattr(asr_client, "urlopen", lambda request, timeout: FakeResponse())
    client = StepFunASRClient(StepFunASRConfig(api_key="step-key"))

    with pytest.raises(RuntimeError, match="bad audio"):
        client.transcribe_bytes(b"audio-bytes", filename="meeting.mp3", content_type="audio/mpeg")


def test_stepfun_asr_client_rejects_unsupported_audio_format_before_request():
    client = StepFunASRClient(StepFunASRConfig(api_key="step-key"))

    with pytest.raises(ValueError, match="supports ogg, mp3, wav, and pcm"):
        client.transcribe_bytes(b"audio-bytes", filename="meeting.webm", content_type="audio/webm")


def test_stepfun_asr_client_rejects_audio_that_would_exceed_sse_base64_limit(monkeypatch):
    called = {"urlopen": False}

    def fake_urlopen(request, timeout):
        called["urlopen"] = True
        raise AssertionError("request should not be sent")

    monkeypatch.setattr(asr_client, "urlopen", fake_urlopen)
    client = StepFunASRClient(StepFunASRConfig(api_key="step-key"))

    with pytest.raises(ValueError, match="base64 audio.data limit is 40MiB"):
        client.transcribe_bytes(
            b"x" * (STEPFUN_MAX_AUDIO_DATA_BYTES + 1),
            filename="meeting.ogg",
            content_type="audio/ogg",
        )

    assert called["urlopen"] is False


def test_stepfun_asr_client_uses_file_api_when_show_utterances_enabled(monkeypatch):
    requests = []
    responses = iter(
        [
            {"task_id": "task-123"},
            {},
            {
                "result": [
                    {
                        "text": "你好",
                        "utterances": [
                            {
                                "text": "你好",
                                "start_time": 0,
                                "end_time": 500,
                                "words": [
                                    {"text": "你", "start_time": 0, "end_time": 200},
                                    {"text": "好", "start_time": 200, "end_time": 500},
                                ],
                            }
                        ],
                    }
                ]
            },
        ]
    )

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        requests.append(
            {
                "url": request.full_url,
                "headers": dict(request.header_items()),
                "payload": json.loads(request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        return FakeResponse(next(responses))

    monkeypatch.setattr(asr_client, "urlopen", fake_urlopen)
    monkeypatch.setattr(asr_client.time, "sleep", lambda seconds: None)
    client = StepFunASRClient(
        StepFunASRConfig(
            api_key="step-key",
            base_url="https://api.stepfun.com",
            model_name="stepaudio-2.5-asr",
            file_model_name="step-asr-1.1",
            timeout_seconds=30,
            show_utterances=True,
        )
    )

    result = client.transcribe_url("https://example.com/meeting.ogg", content_type="audio/ogg")

    assert result["text"] == "你好"
    assert result["utterances"][0]["start_time"] == 0
    assert requests[0]["url"] == "https://api.stepfun.com/v1/audio/asr/file/submit"
    assert requests[0]["payload"]["request"]["show_utterances"] is True
    assert requests[0]["payload"]["request"]["model_name"] == "step-asr-1.1"
    assert requests[1]["url"] == "https://api.stepfun.com/v1/audio/asr/file/query"
    assert requests[1]["payload"] == {"task_id": "task-123"}


def test_stepfun_file_api_polling_backs_off_and_applies_jitter(monkeypatch):
    responses = iter(
        [
            {"task_id": "task-123"},
            {},
            {},
            {},
            {"result": [{"text": "完成"}]},
        ]
    )

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    monkeypatch.setattr(
        asr_client,
        "urlopen",
        lambda request, timeout: FakeResponse(next(responses)),
    )
    now = [0.0]
    sleep_delays = []
    jitter_ranges = []

    def fake_sleep(seconds):
        sleep_delays.append(seconds)
        now[0] += seconds

    def fake_random_uniform(lower, upper):
        jitter_ranges.append((lower, upper))
        return upper

    client = StepFunASRClient(
        StepFunASRConfig(
            api_key="step-key",
            poll_interval_seconds=10.0,
            poll_max_interval_seconds=50.0,
            poll_jitter_ratio=0.1,
            file_timeout_seconds=200,
        ),
        sleep=fake_sleep,
        monotonic=lambda: now[0],
        random_uniform=fake_random_uniform,
    )

    result = client.transcribe_file_url(
        "https://example.com/meeting.ogg",
        content_type="audio/ogg",
    )

    assert result["text"] == "完成"
    assert sleep_delays == pytest.approx([11.0, 22.0, 55.0])
    assert jitter_ranges == pytest.approx([(0.0, 1.0), (0.0, 2.0), (0.0, 5.0)])


def test_stepfun_asr_config_defaults_file_model_to_stepaudio_2_5(monkeypatch):
    monkeypatch.setenv("RECORDFLOW_STEPFUN_API_KEY", "step-key")
    monkeypatch.delenv("RECORDFLOW_STEPFUN_ASR_FILE_MODEL", raising=False)

    config = StepFunASRConfig.from_env()

    assert config.file_model_name == "stepaudio-2.5-asr"


def test_stepfun_asr_config_reads_file_polling_controls(monkeypatch):
    monkeypatch.setenv("RECORDFLOW_STEPFUN_API_KEY", "step-key")
    monkeypatch.setenv("RECORDFLOW_STEPFUN_POLL_INTERVAL_SECONDS", "2.0")
    monkeypatch.setenv("RECORDFLOW_STEPFUN_POLL_MAX_INTERVAL_SECONDS", "12.0")
    monkeypatch.setenv("RECORDFLOW_STEPFUN_POLL_JITTER_RATIO", "0.25")

    config = StepFunASRConfig.from_env()

    assert config.poll_interval_seconds == 2.0
    assert config.poll_max_interval_seconds == 12.0
    assert config.poll_jitter_ratio == 0.25


def test_stepfun_asr_client_prefers_file_api_before_stream_for_supported_file_audio(monkeypatch):
    called = {"file": 0, "stream": 0, "bytes": 0}

    def fake_file(self, url, content_type=None):
        called["file"] += 1
        return {
            "task_id": "file-task-1",
            "text": "file transcript",
            "utterances": [{"text": "file transcript", "start_time": 0, "end_time": 100}],
            "raw_result": {"result": [{"text": "file transcript"}]},
        }

    def fake_stream(self, url, content_type=None):
        called["stream"] += 1
        raise AssertionError("stream path should not be tried before file api")

    def fake_bytes(self, data, filename, content_type=None):
        called["bytes"] += 1
        raise AssertionError("bytes fallback should not be used when file api succeeds")

    monkeypatch.setattr(StepFunASRClient, "transcribe_file_url", fake_file)
    monkeypatch.setattr(StepFunASRClient, "transcribe_stream_url", fake_stream)
    monkeypatch.setattr(StepFunASRClient, "transcribe_bytes", fake_bytes)
    client = StepFunASRClient(
        StepFunASRConfig(api_key="step-key", timeout_seconds=30, show_utterances=True)
    )

    result = client.transcribe_url("https://example.com/meeting.ogg", content_type="audio/ogg")

    assert result["text"] == "file transcript"
    assert called == {"file": 1, "stream": 0, "bytes": 0}


def test_stepfun_asr_client_raises_when_file_task_fails(monkeypatch):
    requests = []
    responses = iter(
        [
            {"task_id": "task-123"},
            {"status": "FAILED"},
        ]
    )

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        requests.append(request.full_url)
        return FakeResponse(next(responses))

    monkeypatch.setattr(asr_client, "urlopen", fake_urlopen)
    monkeypatch.setattr(asr_client.time, "sleep", lambda seconds: None)
    client = StepFunASRClient(
        StepFunASRConfig(api_key="step-key", timeout_seconds=30, show_utterances=True)
    )

    with pytest.raises(RuntimeError, match="file task failed"):
        client.transcribe_file_url("https://example.com/meeting.ogg", content_type="audio/ogg")

    assert requests[0].endswith("/v1/audio/asr/file/submit")
    assert requests[1].endswith("/v1/audio/asr/file/query")


def test_stepfun_asr_client_uses_realtime_stream_with_utterances(monkeypatch):
    events = []

    class FakeConnection:
        def __init__(self):
            self.sent = []
            self.recv_count = 0

        def send(self, message, text=None):
            self.sent.append(json.loads(message))

        def recv(self, timeout=None, decode=None):
            self.recv_count += 1
            if self.recv_count == 1:
                return json.dumps({"type": "session.updated"})
            if self.recv_count == 2:
                return json.dumps(
                    {
                        "type": "conversation.item.input_audio_transcription.delta",
                        "item_id": "item-1",
                        "content_index": 0,
                        "delta": "你好",
                        "start_time": 0,
                        "end_time": 500,
                    }
                )
            return json.dumps(
                {
                    "type": "conversation.item.input_audio_transcription.completed",
                    "item_id": "item-1",
                    "transcript": "你好",
                }
            )

        def close(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_connection = FakeConnection()
    monkeypatch.setattr(asr_client, "connect", lambda *args, **kwargs: fake_connection)
    monkeypatch.setattr(asr_client, "transcode_audio_to_wav_pcm", lambda data, filename, content_type: b"PCM")

    client = StepFunASRClient(
        StepFunASRConfig(
            api_key="step-key",
            base_url="https://api.stepfun.com",
            stream_model_name="step-asr-1.1-stream",
            timeout_seconds=30,
            show_utterances=True,
        )
    )

    result = client.transcribe_stream_bytes(b"audio-bytes", filename="meeting.ogg", content_type="audio/ogg")

    assert result["text"] == "你好"
    assert result["utterances"][0]["start_time"] == 0
    assert fake_connection.sent[0]["type"] == "session.update"
    assert fake_connection.sent[1]["type"] == "input_audio_buffer.append"
    assert fake_connection.sent[2]["type"] == "input_audio_buffer.commit"


def test_request_sse_events_includes_http_error_body(monkeypatch):
    error = HTTPError(
        url="https://api.stepfun.com/v1/audio/asr/sse",
        code=400,
        msg="bad request",
        hdrs=None,
        fp=None,
    )
    error.read = lambda: b'{"error":"bad request"}'
    monkeypatch.setattr(asr_client, "urlopen", lambda request, timeout: (_ for _ in ()).throw(error))
    client = StepFunASRClient(StepFunASRConfig(api_key="step-key"))

    with pytest.raises(RuntimeError, match='HTTP 400: {"error":"bad request"}'):
        client.transcribe_bytes(b"audio-bytes", filename="meeting.ogg", content_type="audio/ogg")


def test_request_bytes_retries_transient_url_errors(monkeypatch):
    attempts = {"count": 0}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"audio-bytes"

    def fake_urlopen(request, timeout):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise URLError("temporary ssl eof")
        return FakeResponse()

    monkeypatch.setattr(asr_client, "urlopen", fake_urlopen)
    monkeypatch.setattr(asr_client.time, "sleep", lambda seconds: None)

    result = asr_client.request_bytes(object(), 30)

    assert result == b"audio-bytes"
    assert attempts["count"] == 2


def test_request_bytes_wraps_repeated_url_errors(monkeypatch):
    monkeypatch.setattr(
        asr_client,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(URLError("temporary ssl eof")),
    )
    monkeypatch.setattr(asr_client.time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="network error"):
        asr_client.request_bytes(object(), 30, attempts=2)
