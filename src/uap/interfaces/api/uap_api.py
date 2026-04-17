"""
PyWebView 对外 API 组合类。

方法按领域拆入 mixins，本模块仅做多重继承聚合，便于审阅与单测桩替换。
"""

from __future__ import annotations

from uap.interfaces.api.base import UAPApiBase
from uap.interfaces.api.mixins_projects import ProjectsApiMixin
from uap.interfaces.api.mixins_prediction import PredictionApiMixin
from uap.interfaces.api.mixins_config import ConfigApiMixin
from uap.interfaces.api.mixins_cards import CardsApiMixin
from uap.interfaces.api.mixins_skills import SkillsApiMixin
from uap.interfaces.api.mixins_filesystem import FilesystemApiMixin
from uap.interfaces.api.mixins_knowledge import KnowledgeApiMixin


class UAPApi(
    UAPApiBase,
    ProjectsApiMixin,
    PredictionApiMixin,
    ConfigApiMixin,
    CardsApiMixin,
    SkillsApiMixin,
    FilesystemApiMixin,
    KnowledgeApiMixin,
):
    """``window.pywebview.api`` 暴露的完整方法集。"""

    pass
