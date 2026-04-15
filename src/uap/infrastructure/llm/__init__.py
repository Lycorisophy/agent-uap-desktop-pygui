"""
UAP LLM 集成（基础设施）：Ollama 客户端与模型抽取。
"""

from uap.infrastructure.llm.factory import create_llm_chat_client
from uap.infrastructure.llm.model_extractor import ModelExtractor, create_default_extractor
from uap.infrastructure.llm.ollama_client import OllamaClient, OllamaConfig
from uap.infrastructure.llm.openai_compatible_client import OpenAICompatibleChatClient
from uap.infrastructure.llm.response_text import assistant_text_from_chat_response

__all__ = [
    "OllamaClient",
    "OllamaConfig",
    "OpenAICompatibleChatClient",
    "create_llm_chat_client",
    "assistant_text_from_chat_response",
    "ModelExtractor",
    "create_default_extractor",
]
