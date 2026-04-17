"""从 ``LLMConfig`` 构造 LangChain ``BaseChatModel``（Ollama 原生 / OpenAI 兼容）。"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from uap.config import LLMConfig


def create_langchain_chat_model(cfg: LLMConfig) -> BaseChatModel:
    """
    - ``provider == ollama`` 且 ``api_mode == native``：``ChatOllama``。
    - 其余：``ChatOpenAI``（OpenAI 兼容 ``/v1/chat/completions``）。
    """
    native_ollama = cfg.provider == "ollama" and cfg.api_mode == "native"
    if native_ollama:
        return ChatOllama(
            base_url=cfg.base_url.rstrip("/"),
            model=cfg.model,
            temperature=cfg.temperature,
            num_predict=cfg.max_tokens,
        )
    if not (cfg.api_key or "").strip():
        raise ValueError(
            f"LLM 提供商「{cfg.provider}」使用 OpenAI 兼容接口，请在设置中填写 API Key。"
        )
    base = (cfg.base_url or "").strip().rstrip("/")
    return ChatOpenAI(
        api_key=cfg.api_key.strip(),
        base_url=base or None,
        model=cfg.model,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
        timeout=120.0,
    )
