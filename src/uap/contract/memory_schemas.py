"""
智能体记忆：与设计指南对齐的领域类型（契约层，无 I/O）。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class KnowledgeType(str, Enum):
    EVENT = "event"
    EVENT_RELATION = "event_relation"
    FACT = "fact"
    KNOWLEDGE_BASE = "knowledge_base"


class EpisodeRecord(BaseModel):
    """SQLite `episodes` 行（简化视图）。"""

    id: str
    project_id: str
    source_type: str = Field(description='如 "chat", "doc_chunk"')
    content: str
    created_at: datetime
    processed: bool = False
    processed_at: Optional[datetime] = None
    ref: Optional[str] = Field(None, description="可选：关联消息或外部 id")


class ExtractionProgressRecord(BaseModel):
    """按项目抽取进度。"""

    project_id: str
    last_episode_id: Optional[str] = None
    last_processed_at: Optional[datetime] = None
    total_episodes_processed: int = 0
    extractor_version: str = "1"
    updated_at: Optional[datetime] = None


class MemoryKnowledgePayload(BaseModel):
    """写入向量库前的结构化片段（与 Milvus 行对应）。"""

    content: str
    knowledge_type: KnowledgeType = KnowledgeType.FACT
    source_episode_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
