"""兼容入口：实现位于 ``uap.core.memory.vector``。"""

from uap.core.memory.vector import (
    EmbeddingService,
    OllamaEmbeddings,
    OpenAIEmbeddings,
    RAGContext,
    SearchResult,
    SentenceTransformerEmbeddings,
    VectorRecord,
    VectorSearchService,
    VectorStore,
    create_embedding_service,
    create_search_service,
    create_vector_store,
)

__all__ = [
    "EmbeddingService",
    "OllamaEmbeddings",
    "OpenAIEmbeddings",
    "RAGContext",
    "SearchResult",
    "SentenceTransformerEmbeddings",
    "VectorRecord",
    "VectorSearchService",
    "VectorStore",
    "create_embedding_service",
    "create_search_service",
    "create_vector_store",
]
