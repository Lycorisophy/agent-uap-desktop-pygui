"""兼容入口：实现位于 ``uap.core.memory.knowledge.milvus_project_kb``。"""

from uap.core.memory.knowledge.milvus_project_kb import (
    INDEX_BUILD_PARAMS,
    SEARCH_PARAMS,
    ProjectKnowledgeService,
    _chunk_text,
    _milvus_lite_import_ok,
    _milvus_standalone_http_uri,
    collection_name,
)

__all__ = [
    "INDEX_BUILD_PARAMS",
    "SEARCH_PARAMS",
    "ProjectKnowledgeService",
    "_chunk_text",
    "_milvus_lite_import_ok",
    "_milvus_standalone_http_uri",
    "collection_name",
]
