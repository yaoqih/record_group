from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://api.stepfun.com"
DEFAULT_MODEL_NAME = "stepaudio-2.5-asr"


def post_json(url: str, api_key: str, payload: dict, timeout: int) -> dict:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def guess_format(audio_url: str) -> str:
    suffix = Path(audio_url.split("?", 1)[0]).suffix.lower()
    mapping = {
        ".wav": "wav",
        ".mp3": "mp3",
        ".ogg": "ogg",
        ".pcm": "pcm",
    }
    audio_format = mapping.get(suffix)
    if not audio_format:
        raise ValueError("Cannot infer audio format from URL suffix. Use one of: .wav .mp3 .ogg .pcm")
    return audio_format


def build_audio_payload(audio_url: str, channel: int) -> dict:
    audio_format = guess_format(audio_url)
    payload = {
        "format": audio_format,
        "url": audio_url,
        "channel": channel,
    }
    if audio_format == "ogg":
        payload["codec"] = "opus"
    elif audio_format == "pcm":
        payload["codec"] = "raw"
        payload["rate"] = 16000
        payload["bits"] = 16
    return payload


def submit_task(
    *,
    base_url: str,
    api_key: str,
    audio_url: str,
    model_name: str,
    show_utterances: bool,
    enable_channel_split: bool,
    channel: int,
    timeout: int,
) -> str:
    payload = {
        "audio": build_audio_payload(audio_url, channel),
        "request": {
            "model_name": model_name,
            "enable_channel_split": enable_channel_split,
            "show_utterances": show_utterances,
        },
    }
    response = post_json(f"{base_url}/v1/audio/asr/file/submit", api_key, payload, timeout)
    task_id = str(response.get("task_id") or "").strip()
    if not task_id:
        raise RuntimeError(f"submit did not return task_id: {response}")
    return task_id


def query_task(*, base_url: str, api_key: str, task_id: str, timeout: int) -> dict:
    return post_json(
        f"{base_url}/v1/audio/asr/file/query",
        api_key,
        {"task_id": task_id},
        timeout,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Minimal StepFun file ASR example: submit a task, then poll until the result is ready."
    )
    parser.add_argument("--audio-url", required=True, help="Publicly reachable audio URL.")
    parser.add_argument("--api-key", default=os.getenv("RECORDFLOW_STEPFUN_API_KEY", "").strip())
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--channel", type=int, default=1)
    parser.add_argument("--show-utterances", action="store_true")
    parser.add_argument("--enable-channel-split", action="store_true")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--max-wait-seconds", type=int, default=600)
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("Missing API key. Pass --api-key or set RECORDFLOW_STEPFUN_API_KEY.")
    if args.enable_channel_split and args.channel != 2:
        raise SystemExit("--enable-channel-split requires --channel 2.")

    task_id = submit_task(
        base_url=args.base_url.rstrip("/"),
        api_key=args.api_key,
        audio_url=args.audio_url,
        model_name=args.model_name,
        show_utterances=args.show_utterances,
        enable_channel_split=args.enable_channel_split,
        channel=args.channel,
        timeout=args.timeout,
    )
    print(json.dumps({"task_id": task_id}, ensure_ascii=False))

    deadline = time.monotonic() + args.max_wait_seconds
    while time.monotonic() < deadline:
        result = query_task(
            base_url=args.base_url.rstrip("/"),
            api_key=args.api_key,
            task_id=task_id,
            timeout=args.timeout,
        )
        status = str(result.get("status") or "").upper()
        if status == "FAILED":
            raise SystemExit(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("result"):
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        time.sleep(args.poll_interval)

    raise SystemExit(f"Timed out waiting for task {task_id}.")


if __name__ == "__main__":
    main()
