"""按 ``storage.milvus_backend`` 构造项目知识库实现。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Union

from uap.settings import UapConfig

if TYPE_CHECKING:
    from uap.core.memory.knowledge.milvus_project_kb import ProjectKnowledgeService
    from uap.core.memory.knowledge.sqlite_vec_project_kb import SqliteVecProjectKnowledgeService

ProjectKnowledgeServiceUnion = Union[
    "ProjectKnowledgeService",
    "SqliteVecProjectKnowledgeService",
]


def create_project_knowledge_service(config: UapConfig) -> ProjectKnowledgeServiceUnion:
    backend = (config.storage.milvus_backend or "lite").strip().lower()
    if backend == "sqlite_vec":
        from uap.core.memory.knowledge.sqlite_vec_project_kb import (
            SqliteVecProjectKnowledgeService,
        )

        return SqliteVecProjectKnowledgeService(config)
    from uap.core.memory.knowledge.milvus_project_kb import ProjectKnowledgeService

    return ProjectKnowledgeService(config)
