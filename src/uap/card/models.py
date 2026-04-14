"""
UAP 卡片确认系统

参考 Chimera 的卡片确认机制，在关键决策点弹出结构化卡片，
让用户做选择题而非自由输入，降低认知负担。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class CardType(str, Enum):
    """卡片类型"""
    # 建模相关
    MODEL_CONFIRM = "model_confirm"           # 模型确认
    VARIABLE_SELECTION = "variable_selection"  # 变量选择
    RELATION_CLARIFICATION = "relation_clarification"  # 关系澄清
    
    # 预测相关
    DATA_SOURCE_SELECTION = "data_source_selection"  # 数据源选择
    METHOD_RECOMMENDATION = "method_recommendation"   # 方法推荐
    PREDICTION_EXECUTION = "prediction_execution"     # 预测执行确认
    
    # 技能相关
    SKILL_SELECTION = "skill_selection"         # 技能选择
    SKILL_SAVE_PROMPT = "skill_save_prompt"   # 技能保存提示
    
    # 高风险操作
    HIGH_RISK_CONFIRM = "high_risk_confirm"   # 高风险操作确认
    LONG_OPERATION_WARNING = "long_operation_warning"  # 长时间操作警告


class CardPriority(str, Enum):
    """卡片优先级"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class CardOption:
    """卡片选项"""
    id: str                           # 选项ID
    label: str                         # 显示标签
    description: Optional[str] = None  # 选项描述
    metadata: dict[str, Any] = field(default_factory=dict)  # 附加数据
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "metadata": self.metadata
        }


@dataclass
class ConfirmationCard:
    """确认卡片"""
    card_id: str                           # 卡片唯一ID
    card_type: CardType                    # 卡片类型
    title: str                             # 卡片标题
    content: str                           # 卡片内容（支持Markdown）
    options: list[CardOption]              # 选项列表
    priority: CardPriority = CardPriority.NORMAL  # 优先级
    default_option_id: Optional[str] = None  # 默认选项ID
    context: dict[str, Any] = field(default_factory=dict)  # 上下文信息
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None  # 过期时间
    requires_confirmation: bool = True      # 是否需要显式确认
    icon: Optional[str] = None              # 图标emoji
    
    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "card_type": self.card_type.value,
            "title": self.title,
            "content": self.content,
            "options": [opt.to_dict() for opt in self.options],
            "priority": self.priority.value,
            "default_option_id": self.default_option_id,
            "context": self.context,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "requires_confirmation": self.requires_confirmation,
            "icon": self.icon
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> ConfirmationCard:
        data = dict(data)
        data["card_type"] = CardType(data["card_type"])
        data["priority"] = CardPriority(data.get("priority", "normal"))
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        if data.get("expires_at"):
            data["expires_at"] = datetime.fromisoformat(data["expires_at"])
        data["options"] = [CardOption(**opt) for opt in data.get("options", [])]
        return cls(**data)


@dataclass
class CardResponse:
    """卡片响应"""
    card_id: str                    # 对应的卡片ID
    selected_option_id: str          # 用户选择的选项ID
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "selected_option_id": self.selected_option_id,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }


@dataclass
class CardContext:
    """卡片上下文"""
    project_id: Optional[str] = None
    session_id: Optional[str] = None
    task_type: Optional[str] = None    # modeling / prediction / analysis
    user_intent: Optional[str] = None
    extracted_model: Optional[dict] = None  # 已提取的模型
    prediction_config: Optional[dict] = None  # 预测配置
    skill_chain: list[str] = field(default_factory=list)  # 技能链
    estimated_time: Optional[int] = None  # 预估时间（秒）
    estimated_cost: Optional[float] = None  # 预估成本
    
    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "session_id": self.session_id,
            "task_type": self.task_type,
            "user_intent": self.user_intent,
            "extracted_model": self.extracted_model,
            "prediction_config": self.prediction_config,
            "skill_chain": self.skill_chain,
            "estimated_time": self.estimated_time,
            "estimated_cost": self.estimated_cost
        }
