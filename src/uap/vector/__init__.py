"""兼容包：实现位于 ``uap.infrastructure.vector``。"""

from uap.infrastructure.vector import (
    VectorStore,
    VectorRecord,
    EmbeddingService,
    OllamaEmbeddings,
    OpenAIEmbeddings,
    SentenceTransformerEmbeddings,
    create_embedding_service,
    VectorSearchService,
    SearchResult,
    RAGContext,
    create_search_service,
    create_vector_store,
)

__all__ = [
    "VectorStore",
    "VectorRecord",
    "EmbeddingService",
    "OllamaEmbeddings",
    "OpenAIEmbeddings",
    "SentenceTransformerEmbeddings",
    "create_embedding_service",
    "VectorSearchService",
    "SearchResult",
    "RAGContext",
    "create_search_service",
    "create_vector_store",
]
