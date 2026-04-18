"""
OllamaClient —— **推理 Harness**：把「消息列表」送到本地 Ollama HTTP API
================================================================

在整体架构中的位置：
- **提示词工程**：上游拼装 ``messages``（system/user）；本类不负责模板内容。
- **上下文工程**：若消息过长，应在调用前依据 ``UapConfig.context_compression`` 截断/摘要。
- **行动模式**：ReAct 每步 ``chat`` 一次；批处理/流式可扩展 ``stream=True`` 分支。

与 **技能系统** 的边界：本模块不解析 Thought/Action；仅传输与错误重试（如有）。
================================================================
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional, Generator

import httpx

# 配置日志
_LOG = logging.getLogger("uap.ollama")
_LOG.setLevel(logging.DEBUG)


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
    **本地 LLM 网关**：同步 HTTP 客户端，供 ``ReactAgent``、``ModelExtractor``、
    ``SkillManager`` 等复用。

    线程安全：``httpx.Client`` 实例不宜跨 asyncio 任务共享；桌面应用主线程一般可接受。
    """

    def __init__(self, config: Optional[OllamaConfig] = None):
        """
        Args:
            config: 含 ``base_url`` / ``model`` / ``timeout``；缺省连本机 11434。
        """
        self.config = config or OllamaConfig()  # 连接与默认模型名
        self.client = httpx.Client(  # 长连接型 **传输层 Harness**
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
        **聊天补全**（Ollama ``/api/chat``）：ReAct / 技能链 / 抽取器共用的最低层调用。

        Args:
            messages: OpenAI 风格消息列表；**上下文工程**在调用前完成截断与角色划分。
            model: 覆盖默认 ``OllamaConfig.model``（便于 A/B 或用户切换）。
            stream: True 时返回生成器，供 UI 流式渲染（需上层消费迭代器）。
            options: 透传 Ollama ``options``（temperature、num_ctx 等）。

        Returns:
            非流式：整包 JSON；流式：逐块 dict 生成器。
        """
        model = model or self.config.model

        payload = {
            "model": model,
            "messages": messages,
            "stream": stream
        }
        if options:
            payload["options"] = options

        _LOG.info("[Ollama] chat request: model=%s, msg_count=%d, stream=%s",
                  model, len(messages), stream)

        # Ollama 原生对话端点（与 OpenAI 兼容路由区分）
        api_path = "/api/chat"
        
        if stream:
            return self._stream_chat(payload, api_path)
        else:
            response = self.client.post(api_path, json=payload)
            _LOG.info("[Ollama] chat response: status=%d", response.status_code)
            result = response.json()
            _LOG.debug("[Ollama] response: %s", str(result)[:200])
            return result
    
    def _stream_chat(self, payload: dict, api_path: str = "/api/chat") -> Generator[dict, None, None]:
        """
        流式聊天请求生成器
        
        Args:
            payload: 请求载荷
            api_path: API路径
            
        Yields:
            dict: 流式响应块
        """
        with self.client.stream("POST", api_path, json=payload) as response:
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
