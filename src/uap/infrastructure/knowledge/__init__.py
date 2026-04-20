"""兼容入口：实现位于 ``uap.core.memory.knowledge``。"""

from uap.core.memory.knowledge import (
    ProjectKnowledgeService,
    SqliteVecProjectKnowledgeService,
    create_project_knowledge_service,
)

__all__ = [
    "ProjectKnowledgeService",
    "SqliteVecProjectKnowledgeService",
    "create_project_knowledge_service",
]
