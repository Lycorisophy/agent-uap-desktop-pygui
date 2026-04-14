"""
UAP LLM集成模块
负责与Ollama等本地大模型服务通信，实现系统模型提取
"""

from uap.llm.ollama_client import OllamaClient
from uap.llm.model_extractor import ModelExtractor

__all__ = ['OllamaClient', 'ModelExtractor']
