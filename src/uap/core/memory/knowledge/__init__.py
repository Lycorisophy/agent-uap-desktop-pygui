"""项目知识库（Milvus / SQLite 向量）。"""

from uap.core.memory.knowledge.factory import create_project_knowledge_service
from uap.core.memory.knowledge.milvus_project_kb import ProjectKnowledgeService
from uap.core.memory.knowledge.sqlite_vec_project_kb import SqliteVecProjectKnowledgeService

__all__ = [
    "ProjectKnowledgeService",
    "SqliteVecProjectKnowledgeService",
    "create_project_knowledge_service",
]
