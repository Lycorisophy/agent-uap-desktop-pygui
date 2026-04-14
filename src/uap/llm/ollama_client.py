"""
Ollama客户端封装
提供与本地Ollama服务的通信接口
"""

import json
from typing import Optional, Generator, Any
from dataclasses import dataclass
from enum import Enum

import httpx


class OllamaModel:
    """Ollama模型信息"""
    
    def __init__(
        self,
        name: str,
        model: str,
        size: int,
        digest: str,
        modified_at: str
    ):
        self.name = name
        self.model = model
        self.size = size
        self.digest = digest
        self.modified_at = modified_at
    
    def __repr__(self):
        return f"OllamaModel(name={self.name}, size={self.size / 1024 / 1024:.1f}MB)"


@dataclass
class OllamaConfig:
    """Ollama连接配置"""
    base_url: str = "http://localhost:11434"
    model: str = "llama3.2"
    embedding_model: str = "nomic-embed-text"
    timeout: int = 120


class OllamaClient:
    """
    Ollama API客户端
    
    提供与Ollama服务通信的封装，支持：
    - 聊天补全
    - 嵌入生成
    - 模型列表查询
    - 服务健康检查
    """
    
    def __init__(self, config: Optional[OllamaConfig] = None):
        self.config = config or OllamaConfig()
        self.client = httpx.Client(
            base_url=self.config.base_url,
            timeout=self.config.timeout
        )
    
    def is_available(self) -> bool:
        """
        检查Ollama服务是否可用
        
        Returns:
            bool: 服务是否可用
        """
        try:
            response = self.client.get("/api/tags")
            return response.status_code == 200
        except Exception:
            return False
    
    def list_models(self) -> list[OllamaModel]:
        """
        获取已安装的模型列表
        
        Returns:
            list[OllamaModel]: 模型列表
        """
        try:
            response = self.client.get("/api/tags")
            if response.status_code != 200:
                return []
            
            data = response.json()
            models = []
            for m in data.get("models", []):
                models.append(OllamaModel(
                    name=m.get("name", ""),
                    model=m.get("model", ""),
                    size=m.get("size", 0),
                    digest=m.get("digest", ""),
                    modified_at=m.get("modified_at", "")
                ))
            return models
        except Exception:
            return []
    
    def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        stream: bool = False,
        options: Optional[dict] = None
    ) -> dict | Generator[dict, None, None]:
        """
        聊天补全请求
        
        Args:
            messages: 消息列表，格式 [{"role": "user", "content": "..."}]
            model: 模型名称，默认使用配置中的模型
            stream: 是否流式返回
            options: 额外选项如 temperature, top_p 等
            
        Returns:
            dict或Generator: 完整响应或流式生成器
        """
        model = model or self.config.model
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream
        }
        if options:
            payload["options"] = options
        
        if stream:
            return self._stream_chat(payload)
        else:
            response = self.client.post("/api/chat", json=payload)
            return response.json()
    
    def _stream_chat(self, payload: dict) -> Generator[dict, None, None]:
        """
        流式聊天请求生成器
        
        Args:
            payload: 请求载荷
            
        Yields:
            dict: 流式响应块
        """
        with self.client.stream("POST", "/api/chat", json=payload) as response:
            for line in response.iter_lines():
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
    
    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        stream: bool = False,
        options: Optional[dict] = None
    ) -> dict | Generator[dict, None, None]:
        """
        文本生成请求（非对话模式）
        
        Args:
            prompt: 输入提示
            model: 模型名称
            system: 系统提示
            stream: 是否流式返回
            options: 额外选项
            
        Returns:
            dict或Generator: 完整响应或流式生成器
        """
        model = model or self.config.model
        
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": stream
        }
        if system:
            payload["system"] = system
        if options:
            payload["options"] = options
        
        if stream:
            return self._stream_generate(payload)
        else:
            response = self.client.post("/api/generate", json=payload)
            return response.json()
    
    def _stream_generate(self, payload: dict) -> Generator[dict, None, None]:
        """流式生成请求生成器"""
        with self.client.stream("POST", "/api/generate", json=payload) as response:
            for line in response.iter_lines():
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
    
    def create_embedding(self, text: str, model: Optional[str] = None) -> list[float]:
        """
        生成文本嵌入向量
        
        Args:
            text: 输入文本
            model: 嵌入模型，默认使用配置中的嵌入模型
            
        Returns:
            list[float]: 嵌入向量
        """
        model = model or self.config.embedding_model
        
        payload = {
            "model": model,
            "prompt": text
        }
        
        try:
            response = self.client.post("/api/embeddings", json=payload)
            if response.status_code == 200:
                data = response.json()
                return data.get("embedding", [])
        except Exception:
            pass
        
        return []
    
    def close(self):
        """关闭客户端连接"""
        self.client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# 全局单例
_global_client: Optional[OllamaClient] = None


def get_ollama_client(config: Optional[OllamaConfig] = None) -> OllamaClient:
    """
    获取Ollama客户端单例
    
    Args:
        config: 可选的配置对象
        
    Returns:
        OllamaClient: 客户端实例
    """
    global _global_client
    if _global_client is None:
        _global_client = OllamaClient(config)
    return _global_client
