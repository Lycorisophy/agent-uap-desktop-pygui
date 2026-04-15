"""
兼容入口：``UAPApi`` 已迁至 ``uap.interfaces``。

保留本模块以便 ``from uap.api import UAPApi`` 与历史文档一致。
"""

from uap.interfaces.api.uap_api import UAPApi

__all__ = ["UAPApi"]
