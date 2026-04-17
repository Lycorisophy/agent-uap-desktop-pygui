"""根据 ``LLMConfig`` 创建聊天客户端（Ollama 原生或 OpenAI 兼容）。"""

from __future__ import annotations

from uap.config import LLMConfig
from uap.infrastructure.llm.langchain_chat_model import _normalize_minimax_model_id
from uap.infrastructure.llm.ollama_client import OllamaClient, OllamaConfig
from uap.infrastructure.llm.openai_compatible_client import OpenAICompatibleChatClient


def create_llm_chat_client(cfg: LLMConfig):
    """
    - ``provider == ollama`` 且 ``api_mode == native``：``OllamaClient``（/api/chat）。
    - 其余提供商或 ``api_mode == openai``：``OpenAICompatibleChatClient``（需 api_key）。
    """
    native_ollama = cfg.provider == "ollama" and cfg.api_mode == "native"
    if native_ollama:
        return OllamaClient(
            OllamaConfig(
                base_url=cfg.base_url,
                model=cfg.model,
                timeout=120,
            )
        )
    if not (cfg.api_key or "").strip():
        raise ValueError(
            f"LLM 提供商「{cfg.provider}」使用 OpenAI 兼容接口，请在设置中填写 API Key。"
        )
    model_id = (cfg.model or "").strip()
    if cfg.provider == "minimax":
        model_id = _normalize_minimax_model_id(model_id)
    return OpenAICompatibleChatClient(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        model=model_id,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
        timeout=120.0,
    )
