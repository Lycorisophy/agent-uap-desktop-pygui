"""
UAP 配置管理模块

参考如意72的 config.py 设计
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator


# LLM 提供商
LLMProvider = Literal["ollama", "minimax", "deepseek", "qwen", "openai"]

# 本地配置覆盖文件名
LOCAL_OVERRIDE_REL = Path(".uap") / "uap.local.yaml"


def local_override_config_path() -> Path:
    """界面保存的 LLM 等覆盖层路径"""
    return Path.home() / LOCAL_OVERRIDE_REL


def llm_provider_presets() -> dict[str, dict[str, str]]:
    """各提供商默认 base_url / 示例 model"""
    return {
        "ollama": {
            "base_url": "http://127.0.0.1:11434",
            "model": "llama3.2",
            "hint": "本地 Ollama",
        },
        "minimax": {
            "base_url": "https://api.minimax.chat/v1",
            "model": "abab6.5s-chat",
            "hint": "MiniMax OpenAI 兼容接口",
        },
        "deepseek": {
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "hint": "DeepSeek",
        },
        "qwen": {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen-turbo",
            "hint": "阿里云 DashScope",
        },
        "openai": {
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "hint": "OpenAI API",
        },
    }


class AppConfig(BaseModel):
    """应用配置"""
    title: str = "UAP - 复杂系统未来势态量化预测统一智能体"
    width: int = Field(default=1280, ge=400, le=4096)
    height: int = Field(default=800, ge=300, le=4096)
    debug: bool = False


class LLMConfig(BaseModel):
    """LLM 配置"""
    provider: LLMProvider = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    model: str = "llama3.2"
    temperature: float = Field(default=0.6, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1, le=262144)
    api_key: Optional[str] = None
    api_mode: Literal["native", "openai"] = "native"
    trust_env: Optional[bool] = None
    
    @field_validator("api_mode", mode="before")
    @classmethod
    def cloud_forces_openai_mode(cls, v: Any, info) -> str:
        if info.data.get("provider") in ("minimax", "deepseek", "qwen", "openai"):
            return "openai"
        return v


class EmbeddingConfig(BaseModel):
    """嵌入模型配置"""
    model: str = "qwen3-embedding:8b"
    base_url: str = ""  # 空则使用 llm.base_url


class StorageConfig(BaseModel):
    """存储配置"""
    # 项目存储根目录，空则使用 ~/.uap/projects
    projects_root: str = ""
    
    # MySQL
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "uap"
    
    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: Optional[str] = None
    redis_db: int = 0
    
    # Elasticsearch
    es_hosts: list[str] = Field(default_factory=lambda: ["http://localhost:9200"])
    es_index_prefix: str = "uap"
    
    # Milvus
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection_prefix: str = "uap"
    
    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    
    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    minio_bucket_prefix: str = "uap"


class PredictionConfig(BaseModel):
    """预测配置"""
    default_frequency_sec: int = Field(default=3600, ge=60, le=86400)
    default_horizon_sec: int = Field(default=259200, ge=3600, le=2592000)
    auto_run_on_startup: bool = True
    max_concurrent_tasks: int = 3
    result_retention_days: int = 30


class SchedulerConfig(BaseModel):
    """调度器配置"""
    enabled: bool = True
    tick_interval_sec: int = Field(default=60, ge=5, le=300)
    max_projects_per_tick: int = 10


class MemoryConfig(BaseModel):
    """记忆与知识系统配置"""
    enabled: bool = True
    vector_enabled: bool = True
    event_index_enabled: bool = True
    graph_enabled: bool = True


class AgentConfig(BaseModel):
    """智能体配置"""
    react_max_steps_default: int = Field(default=12, ge=1, le=200)
    builtin_scheduler_enabled: bool = True


class ContextCompressionConfig(BaseModel):
    """上下文压缩配置"""
    enabled: bool = True
    context_token_budget: int = Field(default=32000, ge=4096, le=500000)
    pre_send_threshold: float = Field(default=0.85, ge=0.3, le=0.99)


class UapConfig(BaseModel):
    """UAP 完整配置"""
    version: int = 1
    app: AppConfig = Field(default_factory=AppConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    prediction: PredictionConfig = Field(default_factory=PredictionConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    context_compression: ContextCompressionConfig = Field(default_factory=ContextCompressionConfig)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """深度合并字典"""
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _default_dict() -> dict[str, Any]:
    """默认配置字典"""
    return UapConfig().model_dump()


def config_search_paths() -> list[Path]:
    """配置文件搜索路径"""
    paths = []
    env = os.environ.get("UAP_CONFIG", "").strip()
    if env:
        paths.append(Path(env).expanduser())
    paths.append(Path.cwd() / "uap.yaml")
    paths.append(Path.cwd() / "config" / "uap.yaml")
    home = Path.home()
    paths.append(home / ".uap" / "uap.yaml")
    return paths


def load_config_file(path: Path) -> dict[str, Any]:
    """加载单个配置文件"""
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"配置文件根节点必须是映射: {path}")
    return data


def load_config() -> UapConfig:
    """
    合并默认配置与首个命中的主 YAML，再合并 ~/.uap/uap.local.yaml
    """
    merged: dict[str, Any] = _default_dict()
    
    # 加载主配置
    for p in config_search_paths():
        try:
            if p.is_file():
                merged = _deep_merge(merged, load_config_file(p))
                break
        except OSError:
            continue
    
    # 加载本地覆盖
    local = local_override_config_path()
    try:
        if local.is_file():
            merged = _deep_merge(merged, load_config_file(local))
    except OSError:
        pass
    
    return UapConfig.model_validate(merged)


def save_llm_local_yaml(llm: LLMConfig) -> Path:
    """将 llm 块写入 ~/.uap/uap.local.yaml"""
    path = local_override_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    
    existing: dict[str, Any] = {}
    try:
        if path.is_file():
            existing = load_config_file(path)
            if not isinstance(existing, dict):
                existing = {}
    except OSError:
        existing = {}
    
    existing["version"] = existing.get("version") or 1
    existing["llm"] = llm.model_dump(mode="json")
    
    text = yaml.safe_dump(
        existing,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    path.write_text(text, encoding="utf-8")
    return path
