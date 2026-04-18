"""
UAP 配置管理模块（兼容入口）。

实现位于 ``uap.settings``：模型见 ``uap.settings.models``，加载见 ``uap.settings.loader``。
"""

from uap.settings import *  # noqa: F403
from uap.settings import __all__ as _settings_all

__all__ = list(_settings_all)
