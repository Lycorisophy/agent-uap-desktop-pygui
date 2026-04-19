"""
对话式技能创建 DST（预留）— 5+1 槽位与统一确认卡流程，详见产品计划。
当前仓库主路径为建模 DstState + 轨迹技能固化；本模块供后续扩展导入。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class SkillCreationConfirmationStatus(str, Enum):
    DRAFT = "draft"
    PENDING_CONFIRM = "pending_confirm"
    CONFIRMED = "confirmed"


class SkillCreationState(BaseModel):
    """占位：intent_action、skill_display_name、skill_trigger_phrases、required_param_schema 等。"""

    intent_action: str = Field(default="CREATE_SKILL")
    skill_display_name: Optional[str] = None
    skill_trigger_phrases: list[str] = Field(default_factory=list)
    required_param_schema: dict[str, Any] = Field(default_factory=dict)
    confirmation_status: SkillCreationConfirmationStatus = SkillCreationConfirmationStatus.DRAFT
    api_endpoint_hint: Optional[str] = None

    class Config:
        use_enum_values = True
