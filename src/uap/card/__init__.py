"""
UAP 卡片确认系统

参考 Chimera 的卡片确认机制，在关键决策点弹出结构化卡片，
让用户做选择题而非自由输入，降低认知负担。

模块结构：
- models: 卡片数据模型
- generator: 卡片生成器
- manager: 卡片生命周期管理
"""

from uap.card.models import (
    CardType,
    CardPriority,
    CardOption,
    ConfirmationCard,
    CardResponse,
    CardContext
)
from uap.card.generator import CardGenerator
from uap.card.manager import CardManager

__all__ = [
    # 模型
    'CardType',
    'CardPriority',
    'CardOption',
    'ConfirmationCard',
    'CardResponse',
    'CardContext',
    # 生成器
    'CardGenerator',
    # 管理器
    'CardManager',
]
