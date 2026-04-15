"""LLM 工厂与响应文本归一化（无外网）。"""

import pytest

from uap.config import LLMConfig
from uap.infrastructure.llm.factory import create_llm_chat_client
from uap.infrastructure.llm.ollama_client import OllamaClient
from uap.infrastructure.llm.response_text import assistant_text_from_chat_response


def test_assistant_text_ollama_shape() -> None:
    r = {"message": {"content": "  hello  "}}
    assert assistant_text_from_chat_response(r).strip() == "hello"


def test_assistant_text_openai_choices_shape() -> None:
    r = {"choices": [{"message": {"content": "x"}}]}
    assert assistant_text_from_chat_response(r) == "x"


def test_assistant_text_plain_string() -> None:
    assert assistant_text_from_chat_response("raw") == "raw"


def test_factory_ollama_native() -> None:
    cfg = LLMConfig(provider="ollama", api_mode="native", base_url="http://127.0.0.1:11434", model="m")
    c = create_llm_chat_client(cfg)
    assert isinstance(c, OllamaClient)


def test_factory_remote_requires_key() -> None:
    cfg = LLMConfig(
        provider="qwen",
        api_mode="openai",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-turbo",
        api_key=None,
    )
    with pytest.raises(ValueError, match="API Key"):
        create_llm_chat_client(cfg)


def test_llm_config_doubao_provider() -> None:
    c = LLMConfig.model_validate(
        {"provider": "doubao", "api_key": "k", "base_url": "https://x", "model": "m"}
    )
    assert c.provider == "doubao"
    assert c.api_mode == "openai"
