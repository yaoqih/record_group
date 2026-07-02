from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://yunwu.ai/v1"
DEFAULT_MODEL = "deepseek-v4-flash"


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_seconds: int = 60

    @classmethod
    def from_env(cls, dotenv_path: Path | str = ".env") -> "LLMConfig":
        load_dotenv(dotenv_path)
        api_key = os.getenv("RECORDFLOW_LLM_API_KEY")
        if not api_key:
            raise ValueError("RECORDFLOW_LLM_API_KEY is required for LLM mode.")
        return cls(
            api_key=api_key,
            base_url=os.getenv("RECORDFLOW_LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            model=os.getenv("RECORDFLOW_LLM_MODEL", DEFAULT_MODEL),
            timeout_seconds=int(os.getenv("RECORDFLOW_LLM_TIMEOUT_SECONDS", "60")),
        )


@dataclass(frozen=True)
class ChatRequest:
    url: str
    headers: dict[str, str]
    body: str
    timeout_seconds: int


class OpenAICompatibleClient:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    def build_chat_request(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> ChatRequest:
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        return ChatRequest(
            url=f"{self.config.base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            body=json.dumps(payload, ensure_ascii=False),
            timeout_seconds=self.config.timeout_seconds,
        )

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        chat_request = self.build_chat_request(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
        )
        request = urllib.request.Request(
            chat_request.url,
            data=chat_request.body.encode("utf-8"),
            headers=chat_request.headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=chat_request.timeout_seconds,
            ) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM request failed: HTTP {exc.code}: {error_body}") from exc

        payload = json.loads(raw)
        content = payload["choices"][0]["message"]["content"]
        return parse_json_content(content)


def parse_json_content(content: str) -> dict[str, Any]:
    stripped = content.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fenced:
        stripped = fenced.group(1).strip()
    return json.loads(stripped)


def load_dotenv(path: Path | str = ".env") -> None:
    dotenv_path = Path(path)
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
