"""从 ``LLMConfig`` 构造 LangChain ``BaseChatModel``（Ollama 原生 / OpenAI 兼容）。"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from uap.settings import LLMConfig


def _normalize_minimax_model_id(raw: str) -> str:
    """
    MiniMax OpenAI 兼容接口要求 ``model`` 为注册名（如 ``MiniMax-M2.7``）。
    常见误填「minimax 2.7」等展示名会导致 400 unknown model。
    """
    s = (raw or "").strip()
    if not s:
        return s
    key = "".join(s.lower().split())
    aliases: dict[str, str] = {
        "minimax2.7": "MiniMax-M2.7",
        "minimaxm2.7": "MiniMax-M2.7",
        "m2.7": "MiniMax-M2.7",
        "minimax2.7highspeed": "MiniMax-M2.7-highspeed",
        "minimaxm2.7highspeed": "MiniMax-M2.7-highspeed",
        "minimax2.5": "MiniMax-M2.5",
        "minimaxm2.5": "MiniMax-M2.5",
        "m2.5": "MiniMax-M2.5",
        "minimax2.5highspeed": "MiniMax-M2.5-highspeed",
        "minimaxm2.5highspeed": "MiniMax-M2.5-highspeed",
        "minimax2.1": "MiniMax-M2.1",
        "minimaxm2.1": "MiniMax-M2.1",
        "m2.1": "MiniMax-M2.1",
        "minimax2.1highspeed": "MiniMax-M2.1-highspeed",
        "minimaxm2.1highspeed": "MiniMax-M2.1-highspeed",
        "minimaxm2": "MiniMax-M2",
        "minimax2": "MiniMax-M2",
        "m2": "MiniMax-M2",
    }
    return aliases.get(key, s)


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
    model_id = (cfg.model or "").strip()
    if cfg.provider == "minimax":
        model_id = _normalize_minimax_model_id(model_id)
    return ChatOpenAI(
        api_key=cfg.api_key.strip(),
        base_url=base or None,
        model=model_id,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
        timeout=120.0,
    )
