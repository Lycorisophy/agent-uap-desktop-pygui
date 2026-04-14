"""
UAP 核心数据模型

定义复杂系统项目管理所需的全部数据模型：
- Project: 复杂系统项目
- SystemModel: 系统数学模型
- PredictionConfig: 预测配置
- PredictionTask: 预测任务
- PredictionResult: 预测结果
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ProjectStatus(str, Enum):
    """项目状态"""
    IDLE = "idle"           # 空闲
    MODELING = "modeling"   # 建模中
    PREDICTING = "predicting"  # 预测中
    ERROR = "error"         # 错误


class ModelSource(str, Enum):
    """模型来源"""
    CONVERSATION = "conversation"  # 对话生成
    DOCUMENT = "document"         # 文档导入
    MANUAL = "manual"             # 手动创建
    IMPORTED = "imported"          # 外部导入


class Variable(BaseModel):
    """系统变量定义"""
    name: str = Field(description="变量名称")
    description: str = Field(default="", description="变量描述")
    unit: str = Field(default="", description="单位")
    value_type: Literal["float", "int", "bool", "str"] = "float"
    initial_range_min: Optional[float] = Field(default=None, description="初始值下界")
    initial_range_max: Optional[float] = Field(default=None, description="初始值上界")
    bounds_min: Optional[float] = Field(default=None, description="值域下界")
    bounds_max: Optional[float] = Field(default=None, description="值域上界")


class Relation(BaseModel):
    """变量关系定义"""
    id: str = Field(default_factory=lambda: f"rel_{uuid.uuid4().hex[:8]}")
    name: str = Field(description="关系名称")
    description: str = Field(default="", description="关系描述")
    relation_type: Literal["equation", "differential", "causal", "correlation"] = "equation"
    # 公式类型：直接表达式
    expression: Optional[str] = Field(default=None, description="数学表达式，如 'dx/dt = -a*x + b*u'")
    # 微分方程参数
    differential_vars: Optional[list[str]] = Field(default=None, description="微分变量列表")
    # 因果关系
    cause_vars: list[str] = Field(default_factory=list, description="因变量列表")
    effect_var: str = Field(description="果变量")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="关系置信度")


class Constraint(BaseModel):
    """约束条件"""
    id: str = Field(default_factory=lambda: f"con_{uuid.uuid4().hex[:8]}")
    name: str = Field(description="约束名称")
    description: str = Field(default="", description="约束描述")
    constraint_type: Literal["equality", "inequality", "boundary"] = "boundary"
    expression: str = Field(description="约束表达式，如 '49.5 <= f <= 50.5'")
    severity: Literal["hard", "soft"] = "hard"
    penalty_weight: Optional[float] = Field(default=None, description="软约束惩罚权重")


class SystemModel(BaseModel):
    """系统数学模型"""
    id: str = Field(default_factory=lambda: f"model_{uuid.uuid4().hex[:8]}")
    name: str = Field(default="", description="模型名称")
    description: str = Field(default="", description="模型描述")
    
    # 核心组成
    variables: list[Variable] = Field(default_factory=list, description="状态变量列表")
    relations: list[Relation] = Field(default_factory=list, description="变量关系列表")
    constraints: list[Constraint] = Field(default_factory=list, description="约束条件列表")
    
    # 模型元数据
    source: ModelSource = ModelSource.CONVERSATION
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="整体模型置信度")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    # 原始数据引用
    source_document_ids: list[str] = Field(default_factory=list, description="来源文档ID")
    source_conversation_ids: list[str] = Field(default_factory=list, description="来源对话ID")
    
    # 建模提示（LLM抽取时的原始提示）
    modeling_prompt: Optional[str] = None
    
    def add_variable(self, var: Variable) -> None:
        """添加变量"""
        self.variables.append(var)
        self.updated_at = datetime.now(timezone.utc).isoformat()
    
    def add_relation(self, rel: Relation) -> None:
        """添加关系"""
        self.relations.append(rel)
        self.updated_at = datetime.now(timezone.utc).isoformat()
    
    def add_constraint(self, con: Constraint) -> None:
        """添加约束"""
        self.constraints.append(con)
        self.updated_at = datetime.now(timezone.utc).isoformat()


class PredictionConfig(BaseModel):
    """预测配置"""
    # 预测频率（秒），默认1小时
    frequency_sec: int = Field(default=3600, ge=60, le=86400)
    # 预测时长（秒），默认3天
    horizon_sec: int = Field(default=259200, ge=3600, le=2592000)
    # 是否启用
    enabled: bool = True
    # 客户端打开时自动预测
    auto_run_on_startup: bool = True
    # 预测方法选择
    method: Literal["auto", "koopman", "pinn", "ensemble"] = "auto"
    # 置信区间置信度
    confidence_level: float = Field(default=0.95, ge=0.5, le=0.99)
    # 数据源配置
    data_source: Literal["workspace", "api", "database"] = "workspace"
    data_workspace_path: Optional[str] = None
    data_api_endpoint: Optional[str] = None
    # 预测结果通知
    notify_on_completion: bool = True
    notify_on_error: bool = True


class Project(BaseModel):
    """复杂系统项目"""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str = Field(description="项目名称")
    description: str = Field(default="", description="项目描述")
    
    # 系统模型
    system_model: Optional[SystemModel] = None
    
    # 预测配置
    prediction_config: PredictionConfig = Field(default_factory=PredictionConfig)
    
    # 项目状态
    status: ProjectStatus = ProjectStatus.IDLE
    
    # 工作区
    workspace: str = Field(default="", description="项目工作区路径")
    
    # 元数据
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    # 最近预测
    last_prediction_at: Optional[str] = None
    last_prediction_status: Literal["success", "failed", "pending"] = "pending"
    
    # 标签
    tags: list[str] = Field(default_factory=list)
    
    # 所有者（未来支持多用户）
    owner_id: Optional[str] = None
    
    def touch(self) -> None:
        """更新修改时间"""
        self.updated_at = datetime.now(timezone.utc).isoformat()
    
    def set_modeling(self) -> None:
        """设为建模状态"""
        self.status = ProjectStatus.MODELING
        self.touch()
    
    def set_predicting(self) -> None:
        """设为预测状态"""
        self.status = ProjectStatus.PREDICTING
        self.touch()
    
    def set_idle(self) -> None:
        """设为空闲状态"""
        self.status = ProjectStatus.IDLE
        self.touch()
    
    def set_error(self, msg: str = "") -> None:
        """设为错误状态"""
        self.status = ProjectStatus.ERROR
        self.touch()
    
    def update_prediction_status(self, success: bool) -> None:
        """更新预测状态"""
        self.last_prediction_at = datetime.now(timezone.utc).isoformat()
        self.last_prediction_status = "success" if success else "failed"
        self.touch()
    
    def to_summary(self) -> dict:
        """项目摘要（用于列表展示）"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "has_model": self.system_model is not None,
            "model_confidence": self.system_model.confidence if self.system_model else None,
            "prediction_enabled": self.prediction_config.enabled,
            "prediction_frequency": self.prediction_config.frequency_sec,
            "last_prediction_at": self.last_prediction_at,
            "last_prediction_status": self.last_prediction_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tags": self.tags,
        }


class PredictionTask(BaseModel):
    """预测任务"""
    id: str = Field(default_factory=lambda: f"pred_{uuid.uuid4().hex[:8]}")
    project_id: str = Field(description="所属项目ID")
    
    # 触发器
    trigger_type: Literal["interval", "daily", "manual", "startup"] = "manual"
    interval_sec: Optional[int] = Field(default=None, ge=60, le=86400)
    daily_time: Optional[str] = Field(default=None, description="HH:MM格式")
    
    # 任务状态
    enabled: bool = True
    next_run_at: Optional[str] = None
    last_run_at: Optional[str] = None
    last_run_status: Literal["success", "failed", "pending"] = "pending"
    last_error: Optional[str] = None
    
    # 运行统计
    run_count: int = 0
    success_count: int = 0
    
    # 标签
    label: str = Field(default="自动预测", description="任务标签")
    
    # 创建时间
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PredictionResult(BaseModel):
    """预测结果"""
    id: str = Field(default_factory=lambda: f"result_{uuid.uuid4().hex[:8]}")
    project_id: str = Field(description="所属项目ID")
    task_id: str = Field(description="关联任务ID")
    
    # 时间信息
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    prediction_time_start: str = Field(description="预测起始时间")
    prediction_time_end: str = Field(description="预测结束时间")
    
    # 预测数据
    # 轨迹数据：时间序列的状态值
    trajectory: list[dict] = Field(default_factory=list, description="预测轨迹点列表")
    
    # 不确定性量化
    confidence_lower: list[float] = Field(default_factory=list, description="置信下界")
    confidence_upper: list[float] = Field(default_factory=list, description="置信上界")
    confidence_level: float = Field(default=0.95, description="置信度")
    
    # 关键指标
    key_metrics: dict[str, Any] = Field(default_factory=dict, description="关键指标值")
    
    # 异常检测
    anomalies: list[dict] = Field(default_factory=list, description="检测到的异常")
    has_anomaly: bool = False
    
    # 系统状态评估
    system_state: Literal["normal", "warning", "critical", "unknown"] = "unknown"
    entropy_value: Optional[float] = Field(default=None, description="系统熵值")
    turbulence_level: Literal["laminar", "transition", "turbulent"] = "laminar"
    
    # 模型信息
    model_id: Optional[str] = None
    method_used: str = "unknown"
    
    # 执行信息
    execution_time_ms: Optional[int] = None
    data_points_used: int = 0
    horizon_achieved: int = 0  # 实际达到的预测时长（秒）
    
    # 状态
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    error_message: Optional[str] = None
    
    def to_summary(self) -> dict:
        """结果摘要"""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "created_at": self.created_at,
            "prediction_horizon": self.horizon_achieved,
            "system_state": self.system_state.value,
            "has_anomaly": self.has_anomaly,
            "entropy_value": self.entropy_value,
            "turbulence_level": self.turbulence_level.value,
            "status": self.status,
            "key_metrics_count": len(self.key_metrics),
            "anomaly_count": len(self.anomalies),
        }
