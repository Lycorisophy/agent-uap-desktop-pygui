"""
UAP LLM 防腐层适配器：Ollama / OpenAI 兼容 / LangChain / 模型抽取。

历史路径 ``uap.infrastructure.llm`` 转发至本包。
"""

from uap.adapters.llm.factory import create_llm_chat_client
from uap.adapters.llm.langchain_chat_model import create_langchain_chat_model
from uap.adapters.llm.model_extractor import ModelExtractor, create_default_extractor
from uap.adapters.llm.ollama_client import OllamaClient, OllamaConfig
from uap.adapters.llm.openai_compatible_client import OpenAICompatibleChatClient
from uap.adapters.llm.response_text import assistant_text_from_chat_response

__all__ = [
    "OllamaClient",
    "OllamaConfig",
    "OpenAICompatibleChatClient",
    "create_llm_chat_client",
    "create_langchain_chat_model",
    "assistant_text_from_chat_response",
    "ModelExtractor",
    "create_default_extractor",
]
