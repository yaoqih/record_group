import json

import pytest

from recordflow_agent.llm_client import (
    LLMConfig,
    OpenAICompatibleClient,
    load_dotenv,
    parse_json_content,
)


def test_llm_config_reads_api_key_from_environment(monkeypatch):
    monkeypatch.setenv("RECORDFLOW_LLM_API_KEY", "test-key")

    config = LLMConfig.from_env()

    assert config.api_key == "test-key"
    assert config.base_url == "https://yunwu.ai/v1"
    assert config.model == "deepseek-v4-flash"


def test_llm_config_rejects_missing_api_key(monkeypatch):
    monkeypatch.setenv("RECORDFLOW_LLM_API_KEY", "")

    with pytest.raises(ValueError, match="RECORDFLOW_LLM_API_KEY"):
        LLMConfig.from_env()


def test_client_builds_openai_compatible_chat_request():
    config = LLMConfig(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
    )
    client = OpenAICompatibleClient(config)

    request = client.build_chat_request(
        system_prompt="Return JSON only.",
        user_prompt="hello",
    )

    assert request.url == "https://example.test/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer test-key"
    assert json.loads(request.body)["model"] == "test-model"


def test_parse_json_content_handles_fenced_json():
    content = """```json
    {"items": [{"type": "Task", "title": "后端"}]}
    ```"""

    assert parse_json_content(content) == {
        "items": [{"type": "Task", "title": "后端"}]
    }


def test_llm_config_loads_values_from_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("RECORDFLOW_LLM_API_KEY", raising=False)
    monkeypatch.delenv("RECORDFLOW_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("RECORDFLOW_LLM_MODEL", raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(
            [
                "RECORDFLOW_LLM_API_KEY=dotenv-key",
                "RECORDFLOW_LLM_BASE_URL=https://yunwu.ai/v1",
                "RECORDFLOW_LLM_MODEL=deepseek-v4-flash",
            ]
        ),
        encoding="utf-8",
    )

    config = LLMConfig.from_env(dotenv_path=dotenv)

    assert config.api_key == "dotenv-key"
    assert config.base_url == "https://yunwu.ai/v1"
    assert config.model == "deepseek-v4-flash"


def test_load_dotenv_does_not_override_existing_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("RECORDFLOW_LLM_MODEL", "env-model")
    dotenv = tmp_path / ".env"
    dotenv.write_text("RECORDFLOW_LLM_MODEL=dotenv-model\n", encoding="utf-8")

    load_dotenv(dotenv)

    assert monkeypatch.context
    assert __import__("os").environ["RECORDFLOW_LLM_MODEL"] == "env-model"
