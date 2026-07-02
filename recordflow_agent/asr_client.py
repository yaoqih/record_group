from __future__ import annotations

import base64
import json
import os
import ssl
import subprocess
import time
import urllib.error
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import tempfile
from urllib.request import Request, urlopen

from recordflow_agent.llm_client import load_dotenv
from recordflow_agent.media_storage import normalize_mime_type
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect


DEFAULT_STEPFUN_BASE_URL = "https://api.stepfun.com"
DEFAULT_STEPFUN_MODEL = "stepaudio-2.5-asr"
DEFAULT_STEPFUN_STREAM_MODEL = "step-asr-1.1-stream"
STEPFUN_MAX_AUDIO_DATA_BYTES = 40 * 1024 * 1024
STEPFUN_MAX_FILE_BYTES = STEPFUN_MAX_AUDIO_DATA_BYTES


@dataclass(frozen=True)
class StepFunASRConfig:
    api_key: str
    base_url: str = DEFAULT_STEPFUN_BASE_URL
    model_name: str = DEFAULT_STEPFUN_MODEL
    file_model_name: str = DEFAULT_STEPFUN_MODEL
    stream_model_name: str = DEFAULT_STEPFUN_STREAM_MODEL
    timeout_seconds: int = 300
    language: str = "zh"
    enable_itn: bool = True
    show_utterances: bool = True
    poll_interval_seconds: float = 1.0
    file_timeout_seconds: int = 1800

    @classmethod
    def from_env(cls, dotenv_path: str = ".env") -> "StepFunASRConfig":
        load_dotenv(dotenv_path)
        api_key = os.getenv("RECORDFLOW_STEPFUN_API_KEY", "").strip()
        if not api_key:
            raise ValueError("RECORDFLOW_STEPFUN_API_KEY is required for ASR mode.")
        return cls(
            api_key=api_key,
            base_url=os.getenv("RECORDFLOW_STEPFUN_BASE_URL", DEFAULT_STEPFUN_BASE_URL).rstrip("/"),
            model_name=os.getenv("RECORDFLOW_STEPFUN_ASR_MODEL", DEFAULT_STEPFUN_MODEL),
            file_model_name=os.getenv("RECORDFLOW_STEPFUN_ASR_FILE_MODEL", DEFAULT_STEPFUN_MODEL),
            stream_model_name=os.getenv(
                "RECORDFLOW_STEPFUN_ASR_STREAM_MODEL", DEFAULT_STEPFUN_STREAM_MODEL
            ),
            timeout_seconds=int(os.getenv("RECORDFLOW_STEPFUN_TIMEOUT_SECONDS", "300")),
            language=os.getenv("RECORDFLOW_STEPFUN_ASR_LANGUAGE", "zh"),
            enable_itn=os.getenv("RECORDFLOW_STEPFUN_ENABLE_ITN", "true").lower()
            not in {"0", "false", "no"},
            show_utterances=os.getenv("RECORDFLOW_STEPFUN_SHOW_UTTERANCES", "true").lower()
            not in {"0", "false", "no"},
            poll_interval_seconds=float(os.getenv("RECORDFLOW_STEPFUN_POLL_INTERVAL_SECONDS", "1.0")),
            file_timeout_seconds=int(os.getenv("RECORDFLOW_STEPFUN_FILE_TIMEOUT_SECONDS", "1800")),
        )


class StepFunASRClient:
    def __init__(self, config: StepFunASRConfig) -> None:
        self.config = config

    @classmethod
    def from_env(cls) -> "StepFunASRClient":
        return cls(StepFunASRConfig.from_env())

    def transcribe_url(self, url: str, content_type: str | None = None) -> dict[str, Any]:
        if self.config.show_utterances:
            if is_stepfun_file_audio(url, content_type):
                try:
                    return self.transcribe_file_url(url, content_type=content_type)
                except Exception:
                    pass
            try:
                return self.transcribe_stream_url(url, content_type=content_type)
            except Exception:
                pass
        data = request_bytes(Request(url, method="GET"), self.config.timeout_seconds)
        filename = PurePosixPath(url.split("?", 1)[0]).name
        return self.transcribe_bytes(data, filename=filename, content_type=content_type)

    def transcribe_stream_url(self, url: str, content_type: str | None = None) -> dict[str, Any]:
        data = request_bytes(Request(url, method="GET"), self.config.timeout_seconds)
        filename = PurePosixPath(url.split("?", 1)[0]).name
        return self.transcribe_stream_bytes(data=data, filename=filename, content_type=content_type)

    def transcribe_stream_bytes(
        self,
        data: bytes,
        filename: str,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        if not data:
            raise ValueError("Audio data is empty.")
        if len(data) > STEPFUN_MAX_AUDIO_DATA_BYTES:
            raise ValueError("StepFun realtime ASR audio limit is 40MiB.")
        pcm_data = transcode_audio_to_wav_pcm(data, filename, content_type)
        request_id = uuid.uuid4().hex
        events = request_stream_events(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            model_name=self.config.stream_model_name,
            language=self.config.language,
            enable_itn=self.config.enable_itn,
            filename=filename,
            audio_data=pcm_data,
            timeout_seconds=self.config.timeout_seconds,
        )
        text = extract_text_from_stream_events(events)
        utterances = extract_utterances_from_stream_events(events)
        completed = next((event for event in reversed(events) if event.get("type") == "conversation.item.input_audio_transcription.completed"), {})
        return {
            "session_id": completed.get("item_id") or request_id,
            "task_id": completed.get("item_id") or request_id,
            "text": text,
            "utterances": utterances,
            "events": events,
            "raw_result": completed or {"events": events},
        }

    def transcribe_file_url(self, url: str, content_type: str | None = None) -> dict[str, Any]:
        submit_request = self.request(
            "/v1/audio/asr/file/submit",
            file_audio_payload(
                url=url,
                content_type=content_type,
                model=self.config.file_model_name,
                show_utterances=self.config.show_utterances,
            ),
            accept="application/json",
        )
        task = request_json(submit_request, self.config.timeout_seconds)
        task_id = str(task.get("task_id") or "").strip()
        if not task_id:
            raise RuntimeError(f"StepFun ASR file submit did not return task_id: {task}")

        deadline = time.monotonic() + self.config.file_timeout_seconds
        while time.monotonic() < deadline:
            query_request = self.request(
                "/v1/audio/asr/file/query",
                {"task_id": task_id},
                accept="application/json",
            )
            response = request_json(query_request, self.config.timeout_seconds)
            status = str(response.get("status") or "").upper()
            if status == "FAILED":
                raise RuntimeError(f"StepFun ASR file task failed for task {task_id}.")
            if response.get("result"):
                return {
                    "session_id": task_id,
                    "task_id": task_id,
                    "text": extract_text(response),
                    "utterances": extract_utterances(response),
                    "raw_result": response,
                }
            time.sleep(self.config.poll_interval_seconds)
        raise RuntimeError(f"StepFun ASR file query timed out for task {task_id}.")

    def transcribe_bytes(
        self,
        data: bytes,
        filename: str,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        if not data:
            raise ValueError("Audio data is empty.")
        if len(data) > STEPFUN_MAX_AUDIO_DATA_BYTES:
            raise ValueError("StepAudio 2.5 ASR SSE base64 audio.data limit is 40MiB.")
        request = self.request(
            "/v1/audio/asr/sse",
            sse_audio_payload(
                data=data,
                filename=filename,
                content_type=content_type,
                model=self.config.model_name,
                language=self.config.language,
                enable_itn=self.config.enable_itn,
            ),
        )
        events = request_sse_events(request, self.config.timeout_seconds)
        text = transcript_text_from_events(events)
        done = next((event for event in reversed(events) if event.get("type") == "transcript.text.done"), {})
        session_id = extract_session_id(events)
        return {
            "session_id": session_id,
            "task_id": session_id,
            "text": text,
            "utterances": [],
            "events": events,
            "raw_result": done or {"events": events},
        }

    def request(self, path: str, payload: dict[str, Any], accept: str = "text/event-stream") -> Request:
        return Request(
            f"{self.config.base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "Accept": accept,
            },
        )


def sse_audio_payload(
    data: bytes,
    filename: str,
    content_type: str | None,
    model: str,
    language: str,
    enable_itn: bool,
) -> dict[str, Any]:
    return {
        "audio": {
            "data": base64.b64encode(data).decode("ascii"),
            "input": {
                "transcription": {
                    "model": model,
                    "language": language,
                    "enable_itn": enable_itn,
                },
                "format": audio_format_payload(filename=filename, content_type=content_type),
            },
        }
    }


def file_audio_payload(
    url: str,
    content_type: str | None,
    model: str,
    show_utterances: bool,
) -> dict[str, Any]:
    return {
        "audio": audio_payload_for_url(url=url, content_type=content_type),
        "request": {
            "model_name": model,
            "enable_channel_split": False,
            "show_utterances": show_utterances,
        },
    }


def stream_session_payload(
    *,
    model_name: str,
    language: str,
    enable_itn: bool,
    event_id: str,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "type": "session.update",
        "session": {
            "audio": {
                "input": {
                    "format": {
                        "type": "pcm",
                        "codec": "pcm_s16le",
                        "rate": 16000,
                        "bits": 16,
                        "channel": 1,
                    },
                    "transcription": {
                        "model": model_name,
                        "language": language,
                        "full_rerun_on_commit": True,
                        "enable_itn": enable_itn,
                    },
                }
            },
        },
    }


def stream_append_payload(audio_data: bytes) -> dict[str, Any]:
    return {
        "event_id": uuid.uuid4().hex,
        "type": "input_audio_buffer.append",
        "audio": base64.b64encode(audio_data).decode("ascii"),
    }


def stream_commit_payload() -> dict[str, Any]:
    return {"event_id": uuid.uuid4().hex, "type": "input_audio_buffer.commit"}


def iter_audio_chunks(audio_data: bytes, chunk_size: int = 32 * 1024) -> list[bytes]:
    return [audio_data[index : index + chunk_size] for index in range(0, len(audio_data), chunk_size)]


def chunk_duration_seconds(chunk: bytes, bytes_per_second: int = 32_000) -> float:
    return max(len(chunk) / float(bytes_per_second), 0.01)


def audio_format_payload(filename: str, content_type: str | None = None) -> dict[str, Any]:
    audio_format = audio_format_for_url(url=filename, content_type=content_type)
    payload: dict[str, Any] = {"type": audio_format}
    if audio_format == "pcm":
        payload.update({"codec": "pcm_s16le", "rate": 16000, "bits": 16, "channel": 1})
    return payload


def transcode_audio_to_wav_pcm(data: bytes, filename: str, content_type: str | None) -> bytes:
    suffix = Path(filename).suffix or ".bin"
    with tempfile.TemporaryDirectory(prefix="recordflow-stream-") as tmpdir:
        input_path = Path(tmpdir) / f"input{suffix}"
        output_path = Path(tmpdir) / "output.wav"
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
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            error = (process.stderr or process.stdout or "").strip()
            raise RuntimeError(f"ffmpeg audio transcode to WAV/PCM failed: {error}")
        output = output_path.read_bytes()
        if not output:
            raise RuntimeError("ffmpeg audio transcode to WAV/PCM produced an empty file.")
        return output


def audio_payload_for_url(url: str, content_type: str | None = None) -> dict[str, Any]:
    audio_format = audio_format_for_url(url=url, content_type=content_type)
    payload: dict[str, Any] = {
        "format": audio_format,
        "url": url,
        "channel": 1,
    }
    if audio_format == "ogg":
        payload["codec"] = "opus"
    elif audio_format == "pcm":
        payload["codec"] = "raw"
        payload["rate"] = 16000
        payload["bits"] = 16
    return payload


def audio_format_for_url(url: str, content_type: str | None = None) -> str:
    suffix = PurePosixPath(url.split("?", 1)[0].lower()).suffix.lstrip(".")
    if suffix in {"wav", "mp3", "ogg", "pcm"}:
        return suffix
    mime_type = normalize_mime_type(content_type)
    if mime_type in {"audio/mpeg", "audio/mp3"}:
        return "mp3"
    if mime_type in {"audio/ogg", "audio/opus"}:
        return "ogg"
    if mime_type in {"audio/wav", "audio/wave", "audio/x-wav"}:
        return "wav"
    if mime_type in {"audio/pcm", "audio/l16"}:
        return "pcm"
    raise ValueError("StepAudio 2.5 ASR supports ogg, mp3, wav, and pcm audio.")


def is_stepfun_direct_audio(filename: str, content_type: str | None = None) -> bool:
    try:
        audio_format_for_url(filename, content_type)
    except ValueError:
        return False
    return True


def is_stepfun_remuxable_audio(filename: str, content_type: str | None = None) -> bool:
    suffix = PurePosixPath(filename.split("?", 1)[0].lower()).suffix
    mime_type = normalize_mime_type(content_type)
    return suffix == ".webm" or mime_type in {"audio/webm", "video/webm"}


def is_stepfun_supported_audio(filename: str, content_type: str | None = None) -> bool:
    return is_stepfun_direct_audio(filename, content_type) or is_stepfun_remuxable_audio(
        filename,
        content_type,
    )


def is_stepfun_file_audio(filename: str, content_type: str | None = None) -> bool:
    try:
        return audio_format_for_url(filename, content_type) in {"wav", "mp3", "ogg", "pcm"}
    except ValueError:
        return False


def request_stream_events(
    *,
    base_url: str,
    api_key: str,
    model_name: str,
    language: str,
    enable_itn: bool,
    filename: str,
    audio_data: bytes,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    ws_url = base_url.replace("https://", "wss://").replace("http://", "ws://")
    ws_url = f"{ws_url}/v1/realtime/asr/stream"
    headers = [("Authorization", f"Bearer {api_key}")]
    events: list[dict[str, Any]] = []
    try:
        with connect(ws_url, additional_headers=headers, open_timeout=timeout_seconds, ping_interval=None) as ws:
            ws.send(
                json.dumps(
                    stream_session_payload(
                        model_name=model_name,
                        language=language,
                        enable_itn=enable_itn,
                        event_id=uuid.uuid4().hex,
                    ),
                    ensure_ascii=False,
                )
            )
            while True:
                raw = ws.recv(timeout=timeout_seconds)
                if raw is None:
                    raise RuntimeError("StepFun realtime ASR did not confirm session update.")
                event = json.loads(raw)
                events.append(event)
                if event.get("type") == "error":
                    raise RuntimeError(
                        f"StepFun realtime ASR request failed: {event.get('message') or event}"
                    )
                if event.get("type") == "session.updated":
                    break
            for chunk in iter_audio_chunks(audio_data):
                ws.send(json.dumps(stream_append_payload(chunk), ensure_ascii=False))
                time.sleep(chunk_duration_seconds(chunk))
            ws.send(json.dumps(stream_commit_payload(), ensure_ascii=False))
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                remaining = max(0.0, deadline - time.monotonic())
                raw = ws.recv(timeout=remaining)
                if raw is None:
                    break
                event = json.loads(raw)
                events.append(event)
                if event.get("type") == "error":
                    raise RuntimeError(
                        f"StepFun realtime ASR request failed: {event.get('message') or event}"
                    )
                if event.get("type") == "conversation.item.input_audio_transcription.completed":
                    break
    except ConnectionClosed:
        if events:
            return events
        raise
    if not events:
        raise RuntimeError("StepFun realtime ASR response did not include any events.")
    return events


def extract_text_from_stream_events(events: list[dict[str, Any]]) -> str:
    completed = next(
        (
            event
            for event in reversed(events)
            if event.get("type") == "conversation.item.input_audio_transcription.completed" and event.get("transcript")
        ),
        {},
    )
    if completed:
        return str(completed.get("transcript", "")).strip()
    text_parts = [
        str(event.get("delta", "")).strip()
        for event in events
        if event.get("type") == "conversation.item.input_audio_transcription.delta" and event.get("delta")
    ]
    return "".join(text_parts).strip()


def extract_utterances_from_stream_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    utterances_by_key: dict[tuple[str | None, int | None], dict[str, Any]] = {}
    for event in events:
        if event.get("type") != "conversation.item.input_audio_transcription.delta":
            continue
        key = (str(event.get("item_id")) if event.get("item_id") else None, event.get("content_index"))
        current = utterances_by_key.get(key)
        start_time = event.get("start_time")
        end_time = event.get("end_time")
        text = str(event.get("delta") or "").strip()
        if current is None:
            current = {
                "speaker": event.get("speaker"),
                "text": text,
                "start_time": start_time,
                "end_time": end_time,
            }
            utterances_by_key[key] = current
            continue
        if text:
            current["text"] = f"{current.get('text', '')}{text}".strip()
        if start_time is not None and current.get("start_time") is None:
            current["start_time"] = start_time
        if end_time is not None:
            current["end_time"] = end_time
    return sorted(utterances_by_key.values(), key=lambda item: (item.get("start_time") is None, item.get("start_time") or 0))


def extract_text(response: dict[str, Any]) -> str:
    if response.get("text"):
        return str(response["text"]).strip()
    if response.get("events"):
        return transcript_text_from_events(response["events"])
    result = response.get("result") or []
    texts = [item.get("text", "").strip() for item in result if item.get("text")]
    return "\n".join(texts).strip()


def extract_utterances(response: dict[str, Any]) -> list[dict[str, Any]]:
    utterances: list[dict[str, Any]] = []
    for item in response.get("result") or []:
        utterances.extend(item.get("utterances") or [])
    return utterances


def request_sse_events(request: Request, timeout_seconds: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    delta_text: list[str] = []
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            for event in iter_sse_json(response):
                event_type = event.get("type")
                if event_type == "error":
                    raise RuntimeError(f"StepFun ASR request failed: {event.get('message') or event}")
                if event_type == "transcript.text.delta":
                    delta_text.append(str(event.get("delta", "")))
                events.append(event)
                if event_type == "transcript.text.done":
                    if "text" not in event:
                        event["text"] = "".join(delta_text).strip()
                    break
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"StepFun ASR request failed: HTTP {exc.code}: {body}") from exc
    if not events:
        raise RuntimeError("StepFun ASR SSE response did not include any events.")
    return events


def iter_sse_json(lines: Any) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    data_lines: list[str] = []
    for raw_line in lines:
        for line in raw_line.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                if data_lines:
                    events.append(parse_sse_data(data_lines))
                    data_lines = []
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].strip())
    if data_lines:
        events.append(parse_sse_data(data_lines))
    return events


def parse_sse_data(data_lines: list[str]) -> dict[str, Any]:
    data = "\n".join(data_lines)
    if data == "[DONE]":
        return {"type": "done"}
    return json.loads(data)


def transcript_text_from_events(events: list[dict[str, Any]]) -> str:
    done_text = next(
        (
            str(event.get("text", "")).strip()
            for event in reversed(events)
            if event.get("type") == "transcript.text.done" and event.get("text")
        ),
        "",
    )
    if done_text:
        return done_text
    return "".join(str(event.get("delta", "")) for event in events).strip()


def extract_session_id(events: list[dict[str, Any]]) -> str | None:
    for event in events:
        meta = event.get("meta") or {}
        session_id = meta.get("session_id")
        if session_id:
            return str(session_id)
    return None


def request_bytes(request: Request, timeout_seconds: int, attempts: int = 3) -> bytes:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Audio download failed: HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, ssl.SSLError) as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
            break
    raise RuntimeError(f"Audio download failed: network error: {last_error}") from last_error


def request_json(request: Request, timeout_seconds: int) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"StepFun request failed: HTTP {exc.code}: {body}") from exc
