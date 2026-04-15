"""
UAP LLM 集成（基础设施）：Ollama 客户端与模型抽取。
"""

from uap.infrastructure.llm.ollama_client import OllamaClient, OllamaConfig
from uap.infrastructure.llm.model_extractor import ModelExtractor, create_default_extractor

__all__ = ["OllamaClient", "OllamaConfig", "ModelExtractor", "create_default_extractor"]
