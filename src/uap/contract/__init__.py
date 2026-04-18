"""
公共实体模型（七域之一）：领域对象与 API 共用形状。

物理定义仍位于 ``uap.project`` / ``uap.card`` / ``uap.skill`` / ``uap.document``；
本包提供统一聚合导入，新代码可 ``from uap.contract import Project, SystemModel``。
"""

from uap.card.models import (
    CardContext,
    CardOption,
    CardPriority,
    CardResponse,
    CardType,
    ConfirmationCard,
)
from uap.project.models import (
    Constraint,
    ModelSource,
    PredictionConfig,
    PredictionResult,
    PredictionTask,
    Project,
    ProjectStatus,
    Relation,
    SystemModel,
    Variable,
)

__all__ = [
    "CardContext",
    "CardOption",
    "CardPriority",
    "CardResponse",
    "CardType",
    "ConfirmationCard",
    "Constraint",
    "ModelSource",
    "PredictionConfig",
    "PredictionResult",
    "PredictionTask",
    "Project",
    "ProjectStatus",
    "Relation",
    "SystemModel",
    "Variable",
]
