"""
UAP 配置（七域之「配置」）。

``uap.config`` 为兼容入口，与本包导出一致。
"""

from uap.settings.loader import (
    LOCAL_OVERRIDE_REL,
    _deep_merge,
    config_search_paths,
    llm_provider_presets,
    load_config,
    load_config_file,
    local_override_config_path,
    save_llm_local_yaml,
)
from uap.settings.models import (
    AgentConfig,
    AppConfig,
    ContextCompressionConfig,
    EmbeddingConfig,
    LLMConfig,
    LLMProvider,
    MemoryConfig,
    PredictionConfig,
    SchedulerConfig,
    StorageConfig,
    UAPConfig,
    UapConfig,
)

__all__ = [
    "LOCAL_OVERRIDE_REL",
    "_deep_merge",
    "AgentConfig",
    "AppConfig",
    "ContextCompressionConfig",
    "EmbeddingConfig",
    "LLMConfig",
    "LLMProvider",
    "MemoryConfig",
    "PredictionConfig",
    "SchedulerConfig",
    "StorageConfig",
    "UAPConfig",
    "UapConfig",
    "config_search_paths",
    "llm_provider_presets",
    "load_config",
    "load_config_file",
    "local_override_config_path",
    "save_llm_local_yaml",
]
