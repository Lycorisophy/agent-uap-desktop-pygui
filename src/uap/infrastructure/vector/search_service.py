"""
VectorSearchService —— **记忆与知识**中的「向量检索层」+ **上下文工程（RAG）**
================================================================================

与 **提示词工程** 的衔接：
- ``RAGContext.to_prompt`` 把检索结果塞进 **system 风格**消息（当前实现）或
  可改为 user 附加段；与 ``ReactAgent`` 的单条 user 大文本策略不同，集成时注意重复。

与 **行动模式**：
- ReAct 可在 ``project_service`` 组装上下文时调用本服务，把 hits 注入 ``extra_context``。

与 **Harness**：
- 可被独立 API 暴露给前端「知识库搜索」；不负责鉴权，调用方控制集合范围。
================================================================================
"""

from datetime import datetime
from typing import List, Optional, Dict, Any, Callable
from dataclasses import dataclass

from uap.infrastructure.vector.vector_store import VectorStore, VectorRecord
from uap.infrastructure.vector.embeddings import EmbeddingService


@dataclass
class SearchResult:
    """
    搜索结果
    
    包含检索到的记录及其相关度分数。
    """
    record: VectorRecord
    score: float          # 相似度分数
    highlights: List[str] = None  # 高亮片段
    
    def __post_init__(self):
        if self.highlights is None:
            self.highlights = []


@dataclass
class RAGContext:
    """
    **RAG 上下文对象**：检索结果 + 原始 query，用于拼装多段 system/user 消息。

    ``to_prompt`` 是 **提示词模板**的一部分：调整前缀「参考文档:」即改变模型对
    引文的信任方式（归因提示 / 防幻觉提示可在此加强）。
    """
    documents: List[SearchResult]  # 已按相似度排序的命中列表
    query: str  # 用户或子 Agent 的原始问题
    created_at: datetime = None  # 组装时间，便于缓存失效策略
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
    
    @property
    def context_text(self) -> str:
        """获取合并的上下文文本"""
        texts = []
        for result in self.documents:
            texts.append(result.record.content)
        return "\n\n---\n\n".join(texts)
    
    def to_prompt(self, system_prompt: str = None) -> List[Dict[str, str]]:
        """
        转换为 LLM Prompt 格式
        
        Args:
            system_prompt: 系统提示词
            
        Returns:
            消息列表
        """
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        # 添加上下文
        context_parts = []
        for i, result in enumerate(self.documents, 1):
            context_parts.append(
                f"[文档 {i}] (相关度: {result.score:.2f})\n{result.record.content}"
            )
        
        context_text = "\n\n".join(context_parts)
        
        messages.append({
            "role": "system",
            "content": f"参考文档:\n{context_text}"
        })
        
        messages.append({
            "role": "user", 
            "content": self.query
        })
        
        return messages


class VectorSearchService:
    """
    向量检索服务
    
    提供高级语义搜索功能：
    - 语义相似度搜索
    - RAG 检索增强
    - 混合搜索（语义 + 关键词）
    - 自动向量化
    """
    
    # 集合名称常量
    COLLECTION_SYSTEM_MODEL = "system_model"
    COLLECTION_CONVERSATION = "conversation"
    COLLECTION_PREDICTION = "prediction"
    COLLECTION_SKILL = "skill"
    COLLECTION_DOCUMENT = "document"
    
    def __init__(
        self,
        vector_store: VectorStore,
        embedding_service: EmbeddingService = None
    ):
        """
        初始化向量检索服务
        
        Args:
            vector_store: 向量存储实例
            embedding_service: 嵌入服务
        """
        self.store = vector_store
        self.embedding = embedding_service
    
    # ==================== 基础搜索 ====================
    
    def semantic_search(
        self,
        collection: str,
        query: str,
        limit: int = 5,
        min_score: float = 0.0,
        metadata_filter: Dict[str, Any] = None
    ) -> List[SearchResult]:
        """
        语义搜索
        
        Args:
            collection: 集合名称
            query: 查询文本
            limit: 返回数量限制
            min_score: 最低相似度分数
            metadata_filter: 元数据过滤条件
            
        Returns:
            搜索结果列表
        """
        results = self.store.search(
            collection=collection,
            query=query,
            limit=limit * 2,  # 多取一些用于过滤
            filter_metadata=metadata_filter
        )
        
        # 过滤并转换结果
        search_results = []
        for record, score in results:
            if score >= min_score:
                search_results.append(SearchResult(
                    record=record,
                    score=score,
                    highlights=self._extract_highlights(record.content, query)
                ))
                
                if len(search_results) >= limit:
                    break
        
        return search_results
    
    def search_by_vector(
        self,
        collection: str,
        vector: List[float],
        limit: int = 5,
        min_score: float = 0.0,
        metadata_filter: Dict[str, Any] = None
    ) -> List[SearchResult]:
        """使用向量搜索"""
        results = self.store.search(
            collection=collection,
            query_vector=vector,
            limit=limit * 2,
            filter_metadata=metadata_filter
        )
        
        search_results = []
        for record, score in results:
            if score >= min_score:
                search_results.append(SearchResult(
                    record=record,
                    score=score
                ))
                
                if len(search_results) >= limit:
                    break
        
        return search_results
    
    def _extract_highlights(
        self,
        content: str,
        query: str,
        context_chars: int = 100
    ) -> List[str]:
        """提取内容中高亮片段"""
        highlights = []
        query_words = query.lower().split()
        
        content_lower = content.lower()
        
        for word in query_words:
            if len(word) < 2:
                continue
            
            idx = content_lower.find(word)
            if idx >= 0:
                start = max(0, idx - context_chars)
                end = min(len(content), idx + len(word) + context_chars)
                
                highlight = content[start:end]
                if start > 0:
                    highlight = "..." + highlight
                if end < len(content):
                    highlight = highlight + "..."
                
                highlights.append(highlight)
        
        return highlights[:3]  # 最多返回3个高亮片段
    
    # ==================== 项目相关搜索 ====================
    
    def search_system_model(
        self,
        project_id: str,
        query: str,
        limit: int = 3
    ) -> List[SearchResult]:
        """搜索项目系统模型"""
        return self.semantic_search(
            collection=self.COLLECTION_SYSTEM_MODEL,
            query=query,
            limit=limit,
            metadata_filter={"project_id": project_id}
        )
    
    def search_conversation(
        self,
        project_id: str,
        query: str,
        limit: int = 5
    ) -> List[SearchResult]:
        """搜索项目对话历史"""
        return self.semantic_search(
            collection=self.COLLECTION_CONVERSATION,
            query=query,
            limit=limit,
            metadata_filter={"project_id": project_id}
        )
    
    def search_predictions(
        self,
        project_id: str,
        query: str,
        limit: int = 3
    ) -> List[SearchResult]:
        """搜索项目预测结果"""
        return self.semantic_search(
            collection=self.COLLECTION_PREDICTION,
            query=query,
            limit=limit,
            metadata_filter={"project_id": project_id}
        )
    
    def search_skills(
        self,
        project_id: str,
        query: str,
        limit: int = 5
    ) -> List[SearchResult]:
        """搜索项目技能"""
        return self.semantic_search(
            collection=self.COLLECTION_SKILL,
            query=query,
            limit=limit,
            metadata_filter={"project_id": project_id}
        )
    
    # ==================== RAG 功能 ====================
    
    def retrieve_for_rag(
        self,
        project_id: str,
        query: str,
        collections: List[str] = None,
        limit_per_collection: int = 3,
        min_score: float = 0.5
    ) -> RAGContext:
        """
        RAG 检索
        
        从多个集合检索相关文档，构建 RAG 上下文。
        
        Args:
            project_id: 项目ID
            query: 查询文本
            collections: 要检索的集合列表（默认所有项目相关集合）
            limit_per_collection: 每个集合的检索数量
            min_score: 最低相似度分数
            
        Returns:
            RAG 上下文
        """
        if collections is None:
            collections = [
                self.COLLECTION_SYSTEM_MODEL,
                self.COLLECTION_CONVERSATION,
                self.COLLECTION_PREDICTION,
                self.COLLECTION_SKILL
            ]
        
        all_results = []
        
        for collection in collections:
            results = self.semantic_search(
                collection=collection,
                query=query,
                limit=limit_per_collection,
                min_score=min_score,
                metadata_filter={"project_id": project_id}
            )
            all_results.extend(results)
        
        # 按分数排序
        all_results.sort(key=lambda x: x.score, reverse=True)
        
        # 取前 N 个
        top_results = all_results[:10]
        
        return RAGContext(
            documents=top_results,
            query=query
        )
    
    def generate_rag_prompt(
        self,
        rag_context: RAGContext,
        system_prompt: str = None
    ) -> List[Dict[str, str]]:
        """
        生成 RAG Prompt
        
        Args:
            rag_context: RAG 上下文
            system_prompt: 系统提示词
            
        Returns:
            消息列表
        """
        return rag_context.to_prompt(system_prompt)
    
    # ==================== 索引操作 ====================
    
    def index_system_model(
        self,
        project_id: str,
        model_content: str,
        model_data: Dict[str, Any] = None
    ) -> str:
        """
        索引系统模型
        
        Args:
            project_id: 项目ID
            model_content: 模型内容文本
            model_data: 模型数据
            
        Returns:
            记录ID
        """
        metadata = {
            "project_id": project_id,
            "type": "system_model"
        }
        
        if model_data:
            metadata.update({
                "variable_count": len(model_data.get("variables", [])),
                "relation_count": len(model_data.get("relations", [])),
                "model_type": model_data.get("model_type", "unknown")
            })
        
        return self.store.insert(
            collection=self.COLLECTION_SYSTEM_MODEL,
            content=model_content,
            metadata=metadata
        )
    
    def index_conversation(
        self,
        project_id: str,
        role: str,
        content: str,
        message_id: str = None
    ) -> str:
        """
        索引对话消息
        
        Args:
            project_id: 项目ID
            role: 角色 (user/assistant/system)
            content: 消息内容
            message_id: 消息ID
            
        Returns:
            记录ID
        """
        return self.store.insert(
            collection=self.COLLECTION_CONVERSATION,
            content=f"[{role}]: {content}",
            metadata={
                "project_id": project_id,
                "role": role,
                "message_id": message_id
            }
        )
    
    def index_prediction(
        self,
        project_id: str,
        prediction_content: str,
        prediction_data: Dict[str, Any] = None
    ) -> str:
        """
        索引预测结果
        
        Args:
            project_id: 项目ID
            prediction_content: 预测内容
            prediction_data: 预测数据
            
        Returns:
            记录ID
        """
        metadata = {
            "project_id": project_id,
            "type": "prediction"
        }
        
        if prediction_data:
            metadata.update({
                "predicted_at": prediction_data.get("predicted_at"),
                "horizon_days": prediction_data.get("horizon_seconds", 0) / 86400,
                "entropy": prediction_data.get("entropy_value"),
                "system_state": prediction_data.get("system_state")
            })
        
        return self.store.insert(
            collection=self.COLLECTION_PREDICTION,
            content=prediction_content,
            metadata=metadata
        )
    
    def index_skill(
        self,
        project_id: str,
        skill_content: str,
        skill_data: Dict[str, Any] = None
    ) -> str:
        """
        索引技能
        
        Args:
            project_id: 项目ID
            skill_content: 技能内容
            skill_data: 技能数据
            
        Returns:
            记录ID
        """
        metadata = {
            "project_id": project_id,
            "type": "skill"
        }
        
        if skill_data:
            metadata.update({
                "skill_name": skill_data.get("name"),
                "category": skill_data.get("category"),
                "confidence": skill_data.get("confidence")
            })
        
        return self.store.insert(
            collection=self.COLLECTION_SKILL,
            content=skill_content,
            metadata=metadata
        )
    
    # ==================== 统计信息 ====================
    
    def get_project_stats(self, project_id: str) -> Dict[str, int]:
        """获取项目向量统计"""
        collections = [
            self.COLLECTION_SYSTEM_MODEL,
            self.COLLECTION_CONVERSATION,
            self.COLLECTION_PREDICTION,
            self.COLLECTION_SKILL
        ]
        
        stats = {}
        for collection in collections:
            count = self.store.count(collection)
            # 过滤项目相关
            filtered_count = 0
            for record in self.store.list(collection):
                if record.metadata.get("project_id") == project_id:
                    filtered_count += 1
            stats[collection] = filtered_count
        
        return stats
    
    def cleanup_project_vectors(self, project_id: str) -> int:
        """
        清理项目的所有向量数据
        
        Args:
            project_id: 项目ID
            
        Returns:
            删除的记录数量
        """
        collections = [
            self.COLLECTION_SYSTEM_MODEL,
            self.COLLECTION_CONVERSATION,
            self.COLLECTION_PREDICTION,
            self.COLLECTION_SKILL
        ]
        
        total_deleted = 0
        
        for collection in collections:
            records = self.store.list(collection)
            for record in records:
                if record.metadata.get("project_id") == project_id:
                    self.store.delete(record.id)
                    total_deleted += 1
        
        return total_deleted


def create_search_service(
    projects_dir: str,
    llm_client = None,
    embedding_provider: str = "ollama",
    **embedding_kwargs
) -> VectorSearchService:
    """
    创建向量检索服务的工厂函数
    
    Args:
        projects_dir: 项目根目录
        llm_client: LLM 客户端
        embedding_provider: 嵌入服务提供商
        **embedding_kwargs: 嵌入服务参数
        
    Returns:
        VectorSearchService 实例
    """
    # 创建嵌入服务
    if embedding_kwargs.get("embedding_service"):
        embedding = embedding_kwargs["embedding_service"]
    else:
        from uap.infrastructure.vector.embeddings import create_embedding_service
        embedding = create_embedding_service(
            provider=embedding_provider,
            llm_client=llm_client,
            **embedding_kwargs
        )
    
    # 创建向量存储
    import os
    db_path = os.path.join(projects_dir, "vectors.db")
    store = VectorStore(
        db_path=db_path,
        embedding_service=embedding,
        dimension=embedding.dimension
    )
    
    return VectorSearchService(store, embedding)
