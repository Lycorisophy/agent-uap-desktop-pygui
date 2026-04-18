"""
配置模型定义（Pydantic）。

加载与合并逻辑见 ``uap.settings.loader``。
"""

from __future__ import annotations

from typing import Any, Literal, Optional

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

    model_config = {"extra": "ignore"}

    projects_root: str = ""
    milvus_lite_path: str = ""
    milvus_backend: Literal["lite", "standalone"] = "lite"
    milvus_use_tls: bool = False
    milvus_token: str = ""

    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "uap"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: Optional[str] = None
    redis_db: int = 0

    es_hosts: list[str] = Field(default_factory=lambda: ["http://localhost:9200"])
    es_index_prefix: str = "uap"

    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection_prefix: str = "uap"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    minio_bucket_prefix: str = "uap"

    @model_validator(mode="before")
    @classmethod
    def _flatten_storage_milvus_yaml(cls, data: Any) -> Any:
        """兼容 YAML 中 ``storage.milvus: { host, port, ... }`` 嵌套写法。"""
        if not isinstance(data, dict):
            return data
        out = dict(data)
        nest = out.pop("milvus", None)
        if isinstance(nest, dict):
            if "host" in nest:
                out["milvus_host"] = nest["host"]
            if "port" in nest:
                out["milvus_port"] = nest["port"]
            if "collection_prefix" in nest:
                out["milvus_collection_prefix"] = nest["collection_prefix"]
            if "backend" in nest:
                out["milvus_backend"] = nest["backend"]
            if "use_tls" in nest:
                out["milvus_use_tls"] = nest["use_tls"]
            if "token" in nest:
                out["milvus_token"] = nest["token"]
        return out


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
    - ``graph_enabled``：为真时随 ``model.json`` 同步写入项目目录 ``entity_graph.json``（本地 JSON 投影，无外部图库）。

    实现注意：各子模块应在启动时读取本块，避免在业务代码里硬编码开关。
    """

    enabled: bool = True
    vector_enabled: bool = True
    event_index_enabled: bool = True
    graph_enabled: bool = True


class AgentConfig(BaseModel):
    """
    **八大行动模式**相关运行时参数（当前仓库以 ReAct 为主）。

    - ``react_max_steps_default``：与 ``ReactAgent.max_iterations`` 语义相同，
      建模 ReAct 单次用户发送内最大 LLM 决策轮数；范围 1–32，默认 8。
    - ``builtin_scheduler_enabled``：定时预测与后台任务，属 **环境 Harness**，
      与对话式行动模式正交。
    - ``modeling_agent_mode``：未传每轮 ``mode`` 时的默认（``react`` / ``plan`` / ``auto``）。
    - ``modeling_skill_solidification_enabled``：是否在 ``business_success`` 时尝试
      ``SkillGenerator`` 落盘项目技能（额外 LLM，默认关闭）。
    """

    react_max_steps_default: int = Field(
        default=8,
        ge=1,
        le=32,
        description="建模 ReAct 单次会话最大决策轮数（与设置页一致，1–32）",
    )
    react_max_time_seconds: float = Field(
        default=300.0,
        ge=30.0,
        le=7200.0,
        description="单次建模 ReAct 会话墙钟超时（秒），与 max_iterations 二选一先触发",
    )
    plan_max_time_seconds: float = Field(
        default=300.0,
        ge=30.0,
        le=7200.0,
        description="单次建模 Plan 图墙钟超时（秒）",
    )
    builtin_scheduler_enabled: bool = True
    modeling_agent_mode: str = Field(
        default="react",
        description="建模默认模式（react/plan/auto）；API 每轮传入的 mode 优先于本字段",
    )
    modeling_kb_tool_enabled: bool = Field(
        default=True,
        description="为建模 ReAct/Plan 注册 search_knowledge（Milvus 项目知识库）工具",
    )
    modeling_intent_context_rounds: int = Field(
        default=2,
        ge=0,
        le=20,
        description="意图/场景分类带入的对话轮数：当前用户句 + 向前最多 N 组 user→assistant；0 关闭 LLM 分类",
    )
    modeling_classifier_llm: Optional[LLMConfig] = Field(
        default=None,
        description="可选；与主 llm 按字段合并后用于意图/场景分类；None 则完全使用主 llm",
    )
    modeling_win11_fs_skills_enabled: bool = Field(
        default=True,
        description="为建模 ReAct/Plan 注册 win11_* 项目内文件读写删改移技能",
    )
    react_max_ask_user_per_turn: int = Field(
        default=1,
        ge=1,
        le=20,
        description=(
            "单次 modeling_chat 内允许连续 ask_user 的次数；达到后图结束，等待用户在下一条消息中回复。"
            "默认 1 表示首轮追问后即结束本轮（HITL），避免同轮无用户输入的死循环追问。"
        ),
    )
    modeling_skill_solidification_enabled: bool = Field(
        default=False,
        description=(
            "为 True 且本轮 ``business_success`` 时，尝试将 DST 轨迹经 SkillGenerator 落盘为项目技能（额外 LLM 调用）"
        ),
    )
    ask_user_card_timeout_seconds: int = Field(
        default=120,
        ge=10,
        le=900,
        description="建模追问卡片（ASK_USER）过期时间（秒），超时视为拒绝并仅写会话、不调 LLM",
    )
    web_search_enabled: bool = Field(
        default=True,
        description="为建模 ReAct/Plan 注册网络搜索技能 web_search",
    )
    web_search_provider: Literal["duckduckgo", "tavily", "mock"] = Field(
        default="duckduckgo",
        description="duckduckgo：免费网页检索；tavily：需填写 tavily_api_key；mock：离线占位",
    )
    tavily_api_key: str = Field(
        default="",
        description="Tavily Search API Key（web_search_provider=tavily 时使用）",
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


# 兼容性别名
UAPConfig = UapConfig
