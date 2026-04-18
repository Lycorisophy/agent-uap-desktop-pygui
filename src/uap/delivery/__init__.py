"""
应用层对外门面：桌面 PyWebView API 等接入点。

实现位于 ``uap.interfaces``；本包提供稳定短路径导入。
"""

from uap.interfaces.api.uap_api import UAPApi

__all__ = ["UAPApi"]
