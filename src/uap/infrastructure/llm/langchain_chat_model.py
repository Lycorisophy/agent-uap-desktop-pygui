"""兼容入口：实现位于 ``uap.adapters.llm.langchain_chat_model``。"""

from uap.adapters.llm.langchain_chat_model import (
    _normalize_minimax_model_id,
    create_langchain_chat_model,
)

__all__ = ["_normalize_minimax_model_id", "create_langchain_chat_model"]
