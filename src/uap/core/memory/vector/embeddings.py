"""
UAP 向量检索系统 - 嵌入服务模块

提供文本到向量的嵌入功能。
支持多种嵌入模型：
- Ollama 本地嵌入 (nomic-embed-text)
- OpenAI 嵌入 (text-embedding-ada-002 等)
"""

from abc import ABC, abstractmethod
from typing import List, Optional
import numpy as np


class EmbeddingService(ABC):
    """
    嵌入服务抽象基类
    
    定义嵌入服务的接口。
    """
    
    @property
    @abstractmethod
    def dimension(self) -> int:
        """返回嵌入向量的维度"""
        pass
    
    @abstractmethod
    def embed(self, text: str) -> List[float]:
        """
        将文本转换为向量
        
        Args:
            text: 输入文本
            
        Returns:
            嵌入向量
        """
        pass
    
    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        批量将文本转换为向量
        
        Args:
            texts: 输入文本列表
            
        Returns:
            嵌入向量列表
        """
        pass
    
    def similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        计算两个向量的余弦相似度
        
        Args:
            vec1: 向量1
            vec2: 向量2
            
        Returns:
            相似度分数 (0-1)
        """
        a = np.array(vec1)
        b = np.array(vec2)
        
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(np.dot(a, b) / (norm_a * norm_b))


class OllamaEmbeddings(EmbeddingService):
    """
    Ollama 嵌入服务
    
    使用 Ollama 本地运行的嵌入模型。
    默认模型: nomic-embed-text (768 维)
    """
    
    def __init__(
        self,
        llm_client,
        model: str = "nomic-embed-text",
        dimension: int = 768
    ):
        """
        初始化 Ollama 嵌入服务
        
        Args:
            llm_client: Ollama 客户端
            model: 嵌入模型名称
            dimension: 向量维度
        """
        self.client = llm_client
        self.model = model
        self._dimension = dimension
    
    @property
    def dimension(self) -> int:
        return self._dimension
    
    def embed(self, text: str) -> List[float]:
        """将文本转换为向量"""
        vector = self.client.create_embedding(text, model=self.model)
        
        if isinstance(vector, dict) and "embedding" in vector:
            return vector["embedding"]
        elif isinstance(vector, list):
            return vector
        
        raise ValueError(f"Unexpected embedding format: {type(vector)}")
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量将文本转换为向量"""
        vectors = []
        
        for text in texts:
            try:
                vector = self.embed(text)
                vectors.append(vector)
            except Exception as e:
                print(f"Failed to embed text: {e}")
                # 返回零向量
                vectors.append([0.0] * self._dimension)
        
        return vectors
    
    def is_available(self) -> bool:
        """检查 Ollama 是否可用"""
        try:
            return self.client.is_available()
        except Exception:
            return False


class OpenAIEmbeddings(EmbeddingService):
    """
    OpenAI 嵌入服务
    
    使用 OpenAI API 的嵌入模型。
    """
    
    # OpenAI 嵌入模型配置
    MODEL_CONFIG = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }
    
    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        base_url: str = "https://api.openai.com/v1"
    ):
        """
        初始化 OpenAI 嵌入服务
        
        Args:
            api_key: OpenAI API Key
            model: 嵌入模型名称
            base_url: API 基础 URL
        """
        import requests
        
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self._dimension = self.MODEL_CONFIG.get(model, 1536)
        
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        })
    
    @property
    def dimension(self) -> int:
        return self._dimension
    
    def embed(self, text: str) -> List[float]:
        """将文本转换为向量"""
        import requests
        
        response = self.session.post(
            f"{self.base_url}/embeddings",
            json={
                "input": text,
                "model": self.model
            }
        )
        
        if response.status_code != 200:
            raise ValueError(f"API error: {response.status_code} - {response.text}")
        
        data = response.json()
        
        if "data" in data and len(data["data"]) > 0:
            return data["data"][0]["embedding"]
        
        raise ValueError(f"Unexpected response format: {data}")
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量将文本转换为向量"""
        import requests
        
        response = self.session.post(
            f"{self.base_url}/embeddings",
            json={
                "input": texts,
                "model": self.model
            }
        )
        
        if response.status_code != 200:
            raise ValueError(f"API error: {response.status_code} - {response.text}")
        
        data = response.json()
        
        vectors = []
        for item in sorted(data["data"], key=lambda x: x["index"]):
            vectors.append(item["embedding"])
        
        return vectors


class SentenceTransformerEmbeddings(EmbeddingService):
    """
    Sentence-Transformer 嵌入服务
    
    使用 sentence-transformers 库的本地嵌入模型。
    """
    
    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        device: str = None
    ):
        """
        初始化 Sentence-Transformer 嵌入服务
        
        Args:
            model_name: 模型名称
            device: 运行设备 ('cpu', 'cuda', 'mps')
        """
        from sentence_transformers import SentenceTransformer
        
        self.model_name = model_name
        
        # 自动选择设备
        if device is None:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
            elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"
        
        self.model = SentenceTransformer(model_name, device=device)
        self._dimension = self.model.get_sentence_embedding_dimension()
    
    @property
    def dimension(self) -> int:
        return self._dimension
    
    def embed(self, text: str) -> List[float]:
        """将文本转换为向量"""
        embedding = self.model.encode(text)
        return embedding.tolist()
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量将文本转换为向量"""
        embeddings = self.model.encode(texts)
        return embeddings.tolist()


def create_embedding_service(
    provider: str = "ollama",
    llm_client = None,
    **kwargs
) -> EmbeddingService:
    """
    创建嵌入服务的工厂函数
    
    Args:
        provider: 提供商 ('ollama', 'openai', 'sentence-transformers')
        llm_client: Ollama 客户端（ollama 提供商时必需）
        **kwargs: 其他参数
        
    Returns:
        EmbeddingService 实例
    """
    if provider == "ollama":
        if llm_client is None:
            raise ValueError("llm_client is required for ollama provider")
        return OllamaEmbeddings(
            llm_client,
            model=kwargs.get("model", "nomic-embed-text"),
            dimension=kwargs.get("dimension", 768)
        )
    
    elif provider == "openai":
        return OpenAIEmbeddings(
            api_key=kwargs["api_key"],
            model=kwargs.get("model", "text-embedding-3-small"),
            base_url=kwargs.get("base_url", "https://api.openai.com/v1")
        )
    
    elif provider == "sentence-transformers":
        return SentenceTransformerEmbeddings(
            model_name=kwargs.get("model_name", "all-MiniLM-L6-v2"),
            device=kwargs.get("device")
        )
    
    else:
        raise ValueError(f"Unknown provider: {provider}")
