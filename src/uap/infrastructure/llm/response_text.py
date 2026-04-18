"""兼容入口：实现位于 ``uap.adapters.llm.response_text``。"""

from uap.adapters.llm.response_text import assistant_text_from_chat_response

__all__ = ["assistant_text_from_chat_response"]
