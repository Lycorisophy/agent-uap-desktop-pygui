"""
OpenAI 兼容 HTTP 聊天客户端（MiniMax / Qwen / 豆包 Ark / Kimi / DeepSeek / OpenAI 等）。
================================================================

通过 ``openai`` SDK 的 ``base_url`` 对接各厂商 ``/v1/chat/completions``；
``chat`` 返回与 Ollama 非流式一致的外层结构：``{"message": {"content": str}}``，
便于 ``ModelExtractor``、``ReactAgent`` 等复用。
================================================================
"""

from __future__ import annotations

import logging
from typing import Any, Generator, Optional

_LOG = logging.getLogger("uap.openai_compatible")


class OpenAICompatibleChatClient:
    """OpenAI Chat Completions 兼容客户端（非流式为主）。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.6,
        max_tokens: int = 4096,
        timeout: float = 120.0,
    ):
        if not (api_key or "").strip():
            raise ValueError(
                "远程 LLM（OpenAI 兼容）需要 api_key，请在应用设置中填写 API Key。"
            )
        from openai import OpenAI

        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        base = (base_url or "").strip().rstrip("/")
        self._client = OpenAI(api_key=api_key.strip(), base_url=base, timeout=timeout)

    def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        stream: bool = False,
        options: Optional[dict] = None,
    ) -> dict | Generator[dict, None, None]:
        if stream:
            raise NotImplementedError("OpenAICompatibleChatClient 暂不支持 stream=True")

        m = model or self._model
        temp = self._temperature
        if options and isinstance(options, dict) and "temperature" in options:
            temp = float(options["temperature"])

        _LOG.info(
            "[OpenAICompat] chat model=%s msgs=%d base=%s",
            m,
            len(messages),
            getattr(self._client, "base_url", ""),
        )
        completion = self._client.chat.completions.create(
            model=m,
            messages=messages,
            temperature=temp,
            max_tokens=self._max_tokens,
        )
        text = ""
        if completion.choices:
            ch0 = completion.choices[0]
            if ch0.message and ch0.message.content is not None:
                text = ch0.message.content
        return {"message": {"content": text or ""}}

    def is_available(self) -> bool:
        """远程服务不做本地探测，视为可用。"""
        return True

    def list_models(self) -> list:
        return []

    def generate(self, *args: Any, **kwargs: Any) -> dict:
        raise NotImplementedError("请使用 chat(messages)")

    def create_embedding(self, text: str, model: Optional[str] = None) -> list[float]:
        _LOG.warning("[OpenAICompat] create_embedding 未实现，返回空向量")
        return []

    def close(self) -> None:
        return

    def __enter__(self) -> OpenAICompatibleChatClient:
        return self

    def __exit__(self, *args: Any) -> None:
        return
