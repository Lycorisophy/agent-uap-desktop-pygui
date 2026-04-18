"""兼容入口：实现位于 ``uap.adapters.llm.model_extractor``。"""

from uap.adapters.llm.model_extractor import ModelExtractor, create_default_extractor

__all__ = ["ModelExtractor", "create_default_extractor"]
