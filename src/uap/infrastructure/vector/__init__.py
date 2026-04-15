"""
UAP 向量检索系统 - 模块入口

提供向量存储、嵌入和语义搜索功能。
基于 sqlite-vss 实现本地向量相似性搜索。
"""

from uap.infrastructure.vector.vector_store import VectorStore, VectorRecord
from uap.infrastructure.vector.embeddings import (
    EmbeddingService,
    OllamaEmbeddings,
    OpenAIEmbeddings,
    SentenceTransformerEmbeddings,
    create_embedding_service,
)
from uap.infrastructure.vector.search_service import (
    VectorSearchService,
    SearchResult,
    RAGContext,
    create_search_service,
)


def create_vector_store(
    db_path: str,
    embedding_service: EmbeddingService = None,
    dimension: int = 768
) -> VectorStore:
    """
    创建向量存储实例
    
    Args:
        db_path: 数据库路径
        embedding_service: 嵌入服务（可选）
        dimension: 向量维度
        
    Returns:
        VectorStore 实例
    """
    return VectorStore(
        db_path=db_path,
        embedding_service=embedding_service,
        dimension=dimension
    )


def create_embedding_service(
    provider: str = "ollama",
    llm_client = None,
    **kwargs
) -> EmbeddingService:
    """
    创建嵌入服务
    
    Args:
        provider: 提供商 ('ollama', 'openai', 'sentence-transformers')
        llm_client: Ollama 客户端（ollama 提供商时必需）
        **kwargs: 其他参数
        
    Returns:
        EmbeddingService 实例
    """
    from uap.infrastructure.vector.embeddings import create_embedding_service as _create
    return _create(provider, llm_client, **kwargs)


def create_search_service(
    projects_dir: str,
    llm_client = None,
    embedding_provider: str = "ollama",
    **embedding_kwargs
) -> VectorSearchService:
    """
    创建向量检索服务
    
    Args:
        projects_dir: 项目根目录
        llm_client: LLM 客户端
        embedding_provider: 嵌入服务提供商
        **embedding_kwargs: 嵌入服务参数
        
    Returns:
        VectorSearchService 实例
    """
    from uap.infrastructure.vector.search_service import create_search_service as _create
    return _create(projects_dir, llm_client, embedding_provider, **embedding_kwargs)


# 导出所有公开接口
__all__ = [
    # 向量存储
    "VectorStore",
    "VectorRecord",
    # 嵌入服务
    "EmbeddingService",
    "OllamaEmbeddings",
    "OpenAIEmbeddings",
    "SentenceTransformerEmbeddings",
    "create_embedding_service",
    # 检索服务
    "VectorSearchService",
    "SearchResult",
    "RAGContext",
    "create_search_service",
    # 快捷创建函数
    "create_vector_store",
    "create_search_service",
]
