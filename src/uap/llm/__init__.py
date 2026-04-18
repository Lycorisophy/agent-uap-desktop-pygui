"""兼容包：LLM 实现位于 ``uap.adapters.llm``（亦见 ``uap.infrastructure.llm``）。"""

from uap.adapters.llm.factory import create_llm_chat_client
from uap.adapters.llm.model_extractor import ModelExtractor, create_default_extractor
from uap.adapters.llm.ollama_client import OllamaClient, OllamaConfig
from uap.adapters.llm.response_text import assistant_text_from_chat_response

__all__ = [
    "OllamaClient",
    "OllamaConfig",
    "create_llm_chat_client",
    "assistant_text_from_chat_response",
    "ModelExtractor",
    "create_default_extractor",
]
