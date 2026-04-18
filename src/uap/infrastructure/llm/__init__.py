"""
兼容入口：LLM 实现已迁至 ``uap.adapters.llm``（防腐层）。

新代码请 ``from uap.adapters.llm import ...``。
"""

from uap.adapters.llm import (
    ModelExtractor,
    OllamaClient,
    OllamaConfig,
    OpenAICompatibleChatClient,
    assistant_text_from_chat_response,
    create_default_extractor,
    create_langchain_chat_model,
    create_llm_chat_client,
)

__all__ = [
    "ModelExtractor",
    "OllamaClient",
    "OllamaConfig",
    "OpenAICompatibleChatClient",
    "assistant_text_from_chat_response",
    "create_default_extractor",
    "create_langchain_chat_model",
    "create_llm_chat_client",
]
