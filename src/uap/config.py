"""
UAP 配置管理模块

参考如意72的 config.py 设计
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator


# LLM 提供商
LLMProvider = Literal[
    "ollama",
    "minimax",
    "deepseek",
    "qwen",
    "openai",
    "doubao",
    "kimi",
]

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
        "doubao": {
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "model": "ep-your-endpoint-id",
            "hint": "豆包/火山方舟：模型名常填推理接入点 Endpoint ID",
        },
        "kimi": {
            "base_url": "https://api.moonshot.cn/v1",
            "model": "moonshot-v1-8k",
            "hint": "Moonshot Kimi OpenAI 兼容接口",
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

    @model_validator(mode="after")
    def remote_providers_use_openai_mode(self) -> "LLMConfig":
        """非 Ollama 厂商一律走 OpenAI 兼容 HTTP；Ollama 默认 native。"""
        if self.provider != "ollama":
            self.api_mode = "openai"
        return self


class EmbeddingConfig(BaseModel):
    """嵌入模型配置（须与 Ollama 模型输出维度一致）"""

    model: str = "qwen3-embedding:8b"
    base_url: str = ""  # 空则使用 llm.base_url
    dimension: int = Field(
        default=4096,
        ge=32,
        le=32768,
        description="向量维度，需与嵌入模型一致（如 qwen3-embedding:8b 常见为 4096）",
    )


class StorageConfig(BaseModel):
    """存储配置"""
    # 项目存储根目录，空则使用 ~/.uap/projects
    projects_root: str = ""
    # Milvus Lite 本地库文件路径，空则使用 ~/.uap/milvus_lite.db
    milvus_lite_path: str = ""
    
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
    """
    **记忆与知识系统**总开关（与 ``docs/设计指南`` 中分层记忆架构对齐的占位配置）。

    - ``vector_enabled``：语义检索 / 长期事实召回（见 ``uap.vector``）。
    - ``event_index_enabled``：时序事件、预测任务等索引（可与 JSONL/SQLite 配合）。
    - ``graph_enabled``：实体关系图存储（当前多为扩展预留，非桌面默认路径）。

    实现注意：各子模块应在启动时读取本块，避免在业务代码里硬编码开关。
    """
    enabled: bool = True  # 总闸：关闭则跳过可选记忆管线，仅保留文件型持久化
    vector_enabled: bool = True  # 向量记忆 / RAG
    event_index_enabled: bool = True  # 事件类记忆索引
    graph_enabled: bool = True  # 图记忆（知识图谱）


class AgentConfig(BaseModel):
    """
    **八大行动模式**相关运行时参数（当前仓库以 ReAct 为主）。

    - ``react_max_steps_default``：与 ``ReactAgent.max_iterations`` 语义类似，
      供上层在创建 Agent 时作为默认安全预算（可在 service 层覆盖）。
    - ``builtin_scheduler_enabled``：定时预测与后台任务，属 **环境 Harness**，
      与对话式行动模式正交。
    - ``modeling_agent_mode``：未传每轮 ``mode`` 时的默认（``react`` / ``plan`` / ``auto``）。
    """
    react_max_steps_default: int = Field(default=12, ge=1, le=200)
    builtin_scheduler_enabled: bool = True
    modeling_agent_mode: str = Field(
        default="react",
        description="建模默认模式（react/plan/auto）；API 每轮传入的 mode 优先于本字段",
    )
    modeling_kb_tool_enabled: bool = Field(
        default=True,
        description="为建模 ReAct/Plan 注册 search_knowledge（Milvus 项目知识库）工具",
    )


class ContextCompressionConfig(BaseModel):
    """
    **上下文工程**：在 ReAct ``decide`` 调用 LLM 前做预算、删除、分级摘要与截断。

    - ``context_token_budget``：单请求目标 token 上限（与模型窗口、成本联动）。
    - ``pre_send_threshold``：估算 token 达到该比例时触发压缩流水线。
    - ``truncation_marker``：硬截断后拼在上下文中的占位符（可配置为 ``<截断>`` 等）。
    """
    enabled: bool = True
    context_token_budget: int = Field(default=32000, ge=4096, le=500000)
    pre_send_threshold: float = Field(default=0.85, ge=0.3, le=0.99)
    truncation_marker: str = Field(default="[[UAP_TRUNCATED]]", max_length=64)
    max_trajectory_steps: int = Field(default=8, ge=1, le=200)
    trajectory_thought_max_chars: int = Field(default=400, ge=50, le=8000)
    trajectory_observation_max_chars: int = Field(default=400, ge=50, le=8000)
    summarize_max_tokens_per_call: int = Field(default=512, ge=64, le=4096)
    enable_llm_summarization: bool = Field(default=True)
    enable_redaction: bool = Field(default=True)
    enable_async_truncation_kb: bool = Field(default=True)
    summarization_min_priority: int = Field(
        default=2,
        ge=2,
        le=5,
        description="仅对 priority>=该值的片段调用 LLM 摘要（2=system_model 起，5=仅 trajectory）",
    )


class UapConfig(BaseModel):
    """
    **UAP 完整配置**：桌面应用 + LLM + 存储 + 预测调度 + 记忆/上下文策略的统一入口。

    扩展「行动模式 / 工具系统」时，优先增加独立子模型（如 ``AgentConfig``），避免
    在 ``LLMConfig`` 中混入非 LLM 字段，便于 **Harness**（`api`/`app`）注入依赖。
    """
    version: int = 1  # 配置文件模式版本，便于迁移
    app: AppConfig = Field(default_factory=AppConfig)  # 窗口与调试等 **桌面壳** 参数
    llm: LLMConfig = Field(default_factory=LLMConfig)  # **提示词载体**所调用的推理端
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)  # 向量记忆嵌入
    storage: StorageConfig = Field(default_factory=StorageConfig)  # 项目根路径等
    prediction: PredictionConfig = Field(default_factory=PredictionConfig)  # 预测默认策略
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)  # 定时 **任务 Harness**
    memory: MemoryConfig = Field(default_factory=MemoryConfig)  # 记忆与知识子系统
    agent: AgentConfig = Field(default_factory=AgentConfig)  # 行动模式默认参数
    context_compression: ContextCompressionConfig = Field(default_factory=ContextCompressionConfig)


# 兼容性别名
UAPConfig = UapConfig


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
