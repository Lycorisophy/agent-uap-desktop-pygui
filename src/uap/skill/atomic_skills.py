"""
UAP 原子技能库 —— **技能与工具系统**中的「可注册可执行」最小单元
================================================================

与设计角色的关系：

- **对 ReAct / Plan 等行动模式**：每个 ``AtomicSkill`` 即一个 **Tool**；``skill_id``
  出现在提示词的技能列表中，模型输出 ``Action: <skill_id>`` 后由 ``ReactAgent``
  分发到 ``execute``。
- **提示词工程**：``SkillMetadata.description`` + ``input_schema`` 构成模型所见的
  工具说明；应保持「短描述 + 明确 JSON 字段名」。
- **Harness**：动态技能（如 ``project_service`` 里注入的 extract/define 系列）
  在运行时 ``set_executor``，把 **业务逻辑** 挂到 **元数据壳** 上。

分类（``SkillCategory``）沿用 Chimera 风格，便于与模板、链式推荐（``get_skill_chain_recommendations``）对齐。
================================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional


class SkillCategory(str, Enum):
    """技能分类（参考 Chimera）"""
    DATA = "data"                    # 数据获取
    PREPROCESSING = "preprocessing"  # 数据预处理
    FEATURE = "feature"             # 特征工程
    MODEL = "model"                 # 模型训练（ML 流水线）
    MODELING = "modeling"           # 复杂系统建模（与 uap.skill.models.SkillCategory 对齐）
    TOOL = "tool"                    # 智能体原生工具（文件访问等，与 file_access_skill 对齐）
    POSTPROCESS = "postprocess"     # 后处理
    ANALYSIS = "analysis"           # 分析
    VISUALIZATION = "visualization"  # 可视化
    GENERAL = "general"             # 通用


class SkillComplexity(str, Enum):
    """技能复杂度"""
    SIMPLE = "simple"      # 简单操作
    MODERATE = "moderate"  # 中等复杂度
    COMPLEX = "complex"    # 复杂操作


@dataclass
class SkillMetadata:
    """
    **技能元数据**：供 UI 列表、LLM 工具说明、前置校验三处复用。

    ``input_schema`` 建议使用 JSON Schema 子集（字段名、类型、是否 required），
    与 ``AtomicSkill.validate_input`` 的规则保持一致，减少 **提示词与实现漂移**。
    """
    skill_id: str                           # 与 ReAct Action 对齐的主键
    name: str                                # 人类可读短名（UI）
    description: str                          # **提示词**用：一句话说明副作用与输入期望
    category: SkillCategory                   # 分组与统计用
    subcategory: Optional[str] = None        # 细分类（可选）

    # --- 规格：连接「模型幻想出的参数」与真实 Python 签名 ---
    input_schema: dict[str, Any] = field(default_factory=dict)   # 输入 JSON 形状说明
    output_schema: dict[str, Any] = field(default_factory=dict)  # 输出形状（文档/校验用）

    # --- 运行时策略 ---
    estimated_time: int = 30                  # 调度与 UI 预估
    complexity: SkillComplexity = SkillComplexity.MODERATE
    requires_confirmation: bool = False       # **HITL**：为 True 时 ReAct 不直接执行
    requires_gpu: bool = False               # 资源声明（当前未强校验）

    # --- 技能链 / 规划（若接入 Plan 模式）---
    required_skills: list[str] = field(default_factory=list)  # 前置技能 id
    provides_skills: list[str] = field(default_factory=list)  # 完成后解锁的能力标签

    # --- 版本与审计 ---
    version: str = "1.0"
    author: str = "system"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "subcategory": self.subcategory,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "estimated_time": self.estimated_time,
            "complexity": self.complexity.value,
            "requires_confirmation": self.requires_confirmation,
            "requires_gpu": self.requires_gpu,
            "required_skills": self.required_skills,
            "provides_skills": self.provides_skills,
            "version": self.version,
            "author": self.author,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }


class AtomicSkill:
    """
    **原子技能实例**：元数据 + 可选 ``_executor``（默认库内为占位实现）。

    执行路径：``ReactAgent._execute_skill`` → ``validate_input`` → ``execute``；
    若需写回 DST，请在 ``execute`` 返回 dict 中带 ``metadata`` 字段（由具体技能约定）。
    """

    def __init__(self, metadata: SkillMetadata):
        self.metadata = metadata  # 对外只读语义；勿在 execute 内改 id，避免注册表不一致
        self._executor: Optional[Callable] = None  # **Harness 注入点**：业务闭包
    
    def set_executor(self, executor: Callable):
        """设置执行器"""
        self._executor = executor
    
    def execute(self, **kwargs) -> dict:
        """执行技能"""
        if self._executor:
            return self._executor(self, **kwargs)
        raise NotImplementedError(f"Skill {self.metadata.skill_id} has no executor")
    
    def validate_input(self, **kwargs) -> tuple[bool, list[str]]:
        """验证输入参数"""
        errors = []
        required = self.metadata.input_schema.get("required", [])
        
        for field_name in required:
            if field_name not in kwargs:
                errors.append(f"Missing required field: {field_name}")
        
        return len(errors) == 0, errors
    
    def estimate_cost(self, **kwargs) -> float:
        """估算执行成本（本地优先，返回0）"""
        # 本地优先模式，无API成本
        return 0.0


# ==================== 预定义原子技能库 ====================

def get_atomic_skills_library() -> dict[str, SkillMetadata]:
    """
    获取预定义的原子技能库
    
    Returns:
        skill_id -> SkillMetadata 映射
    """
    skills = {}
    
    # ==================== 数据获取类 ====================
    
    skills["data_load_csv"] = SkillMetadata(
        skill_id="data_load_csv",
        name="加载CSV数据",
        description="从CSV文件加载时序数据，支持自定义分隔符和编码",
        category=SkillCategory.DATA,
        subcategory="file",
        input_schema={
            "type": "object",
            "required": ["file_path"],
            "properties": {
                "file_path": {"type": "string", "description": "CSV文件路径"},
                "separator": {"type": "string", "default": ","},
                "encoding": {"type": "string", "default": "utf-8"}
            }
        },
        output_schema={
            "type": "object",
            "properties": {
                "data": {"type": "DataFrame"},
                "columns": {"type": "array"}
            }
        },
        estimated_time=5,
        complexity=SkillComplexity.SIMPLE
    )
    
    skills["data_load_json"] = SkillMetadata(
        skill_id="data_load_json",
        name="加载JSON数据",
        description="从JSON文件或API响应加载结构化数据",
        category=SkillCategory.DATA,
        subcategory="file",
        input_schema={
            "type": "object",
            "required": ["source"],
            "properties": {
                "source": {"type": "string", "description": "文件路径或URL"},
                "is_url": {"type": "boolean", "default": False}
            }
        },
        estimated_time=5,
        complexity=SkillComplexity.SIMPLE
    )
    
    skills["data_synthetic"] = SkillMetadata(
        skill_id="data_synthetic",
        name="生成合成数据",
        description="基于系统模型生成合成观测数据",
        category=SkillCategory.DATA,
        subcategory="generation",
        input_schema={
            "type": "object",
            "required": ["model"],
            "properties": {
                "model": {"type": "object", "description": "系统模型定义"},
                "num_points": {"type": "integer", "default": 1000},
                "noise_level": {"type": "number", "default": 0.1}
            }
        },
        estimated_time=10,
        complexity=SkillComplexity.MODERATE
    )
    
    # ==================== 预处理类 ====================
    
    skills["preprocess_missing"] = SkillMetadata(
        skill_id="preprocess_missing",
        name="缺失值处理",
        description="插值填补缺失值，支持线性、样条、均值等多种方法",
        category=SkillCategory.PREPROCESSING,
        subcategory="cleaning",
        input_schema={
            "type": "object",
            "required": ["data", "method"],
            "properties": {
                "data": {"type": "DataFrame"},
                "method": {"type": "string", "enum": ["linear", "spline", "mean", "forward", "backward"]},
                "max_gap": {"type": "integer", "default": 10}
            }
        },
        estimated_time=5,
        complexity=SkillComplexity.SIMPLE
    )
    
    skills["preprocess_outlier"] = SkillMetadata(
        skill_id="preprocess_outlier",
        name="异常值检测",
        description="基于IQR或Z-score剔除异常值",
        category=SkillCategory.PREPROCESSING,
        subcategory="cleaning",
        input_schema={
            "type": "object",
            "required": ["data", "method"],
            "properties": {
                "data": {"type": "DataFrame"},
                "method": {"type": "string", "enum": ["iqr", "zscore"]},
                "threshold": {"type": "number", "default": 3.0}
            }
        },
        estimated_time=5,
        complexity=SkillComplexity.SIMPLE
    )
    
    skills["preprocess_normalize"] = SkillMetadata(
        skill_id="preprocess_normalize",
        name="数据标准化",
        description="Min-Max或Z-score标准化",
        category=SkillCategory.PREPROCESSING,
        subcategory="transform",
        input_schema={
            "type": "object",
            "required": ["data", "method"],
            "properties": {
                "data": {"type": "DataFrame"},
                "method": {"type": "string", "enum": ["minmax", "zscore"]}
            }
        },
        estimated_time=3,
        complexity=SkillComplexity.SIMPLE
    )
    
    skills["preprocess_resample"] = SkillMetadata(
        skill_id="preprocess_resample",
        name="时间重采样",
        description="时间序列重采样，支持上采样和下采样",
        category=SkillCategory.PREPROCESSING,
        subcategory="transform",
        input_schema={
            "type": "object",
            "required": ["data", "frequency"],
            "properties": {
                "data": {"type": "DataFrame"},
                "frequency": {"type": "string", "description": "目标频率如'1H', '1D'"},
                "method": {"type": "string", "enum": ["interpolate", "aggregate", "pad"]}
            }
        },
        estimated_time=5,
        complexity=SkillComplexity.MODERATE
    )
    
    # ==================== 特征工程类 ====================
    
    skills["feature_delay_embedding"] = SkillMetadata(
        skill_id="feature_delay_embedding",
        name="延迟嵌入",
        description="Takens延迟嵌入，生成Hankel矩阵用于Koopman分析",
        category=SkillCategory.FEATURE,
        subcategory="temporal",
        input_schema={
            "type": "object",
            "required": ["data"],
            "properties": {
                "data": {"type": "array"},
                "embedding_dim": {"type": "integer", "default": 10},
                "time_delay": {"type": "integer", "default": 1}
            }
        },
        output_schema={
            "type": "object",
            "properties": {
                "hankel_matrix": {"type": "array"},
                "embedding_dim": {"type": "integer"},
                "time_delay": {"type": "integer"}
            }
        },
        estimated_time=10,
        complexity=SkillComplexity.MODERATE
    )
    
    skills["feature_fft"] = SkillMetadata(
        skill_id="feature_fft",
        name="频域分析",
        description="FFT变换提取频域特征",
        category=SkillCategory.FEATURE,
        subcategory="frequency",
        input_schema={
            "type": "object",
            "required": ["data"],
            "properties": {
                "data": {"type": "array"},
                "sampling_rate": {"type": "number"}
            }
        },
        estimated_time=5,
        complexity=SkillComplexity.SIMPLE
    )
    
    skills["feature_derivative"] = SkillMetadata(
        skill_id="feature_derivative",
        name="数值微分",
        description="计算数值导数，用于Neural ODE",
        category=SkillCategory.FEATURE,
        subcategory="temporal",
        input_schema={
            "type": "object",
            "required": ["data"],
            "properties": {
                "data": {"type": "array"},
                "method": {"type": "string", "enum": ["finite_diff", "spline"]}
            }
        },
        estimated_time=5,
        complexity=SkillComplexity.SIMPLE
    )
    
    skills["feature_entropy"] = SkillMetadata(
        skill_id="feature_entropy",
        name="熵特征",
        description="计算排列熵、多尺度熵等复杂度特征",
        category=SkillCategory.FEATURE,
        subcategory="complexity",
        input_schema={
            "type": "object",
            "required": ["data"],
            "properties": {
                "data": {"type": "array"},
                "entropy_type": {"type": "string", "enum": ["permutation", "sample", "multi_scale"]},
                "scale": {"type": "integer", "default": 5}
            }
        },
        estimated_time=15,
        complexity=SkillComplexity.MODERATE
    )
    
    # ==================== 模型类 ====================
    
    skills["model_koopman_dmd"] = SkillMetadata(
        skill_id="model_koopman_dmd",
        name="Koopman DMD",
        description="动态模式分解，训练Koopman算子",
        category=SkillCategory.MODEL,
        subcategory="koopman",
        input_schema={
            "type": "object",
            "required": ["data"],
            "properties": {
                "data": {"type": "array"},
                "rank": {"type": "integer", "default": 10}
            }
        },
        output_schema={
            "type": "object",
            "properties": {
                "koopman_operator": {"type": "array"},
                "eigenvalues": {"type": "array"},
                "modes": {"type": "array"}
            }
        },
        estimated_time=30,
        complexity=SkillComplexity.COMPLEX,
        requires_gpu=False
    )
    
    skills["model_koopman_edmd"] = SkillMetadata(
        skill_id="model_koopman_edmd",
        name="Extended Koopman DMD",
        description="扩展DMD，使用字典函数逼近非线性",
        category=SkillCategory.MODEL,
        subcategory="koopman",
        input_schema={
            "type": "object",
            "required": ["data", "dict_type"],
            "properties": {
                "data": {"type": "array"},
                "dict_type": {"type": "string", "enum": ["polynomial", "rbf", "fourier"]},
                "rank": {"type": "integer", "default": 20}
            }
        },
        estimated_time=60,
        complexity=SkillComplexity.COMPLEX,
        requires_confirmation=True,
        requires_gpu=False
    )
    
    skills["model_neural_ode"] = SkillMetadata(
        skill_id="model_neural_ode",
        name="Neural ODE",
        description="训练神经常微分方程模型",
        category=SkillCategory.MODEL,
        subcategory="neural",
        input_schema={
            "type": "object",
            "required": ["data"],
            "properties": {
                "data": {"type": "array"},
                "hidden_dim": {"type": "integer", "default": 64},
                "epochs": {"type": "integer", "default": 100}
            }
        },
        estimated_time=120,
        complexity=SkillComplexity.COMPLEX,
        requires_confirmation=True,
        requires_gpu=True
    )
    
    skills["model_monte_carlo"] = SkillMetadata(
        skill_id="model_monte_carlo",
        name="Monte Carlo 模拟",
        description="蒙特卡洛采样估计系统状态分布",
        category=SkillCategory.MODEL,
        subcategory="stochastic",
        input_schema={
            "type": "object",
            "required": ["model", "num_samples"],
            "properties": {
                "model": {"type": "object"},
                "num_samples": {"type": "integer", "default": 1000},
                "noise_covariance": {"type": "array"}
            }
        },
        estimated_time=60,
        complexity=SkillComplexity.MODERATE,
        requires_gpu=False
    )
    
    skills["model_pinn"] = SkillMetadata(
        skill_id="model_pinn",
        name="Physics-Informed NN",
        description="物理信息神经网络",
        category=SkillCategory.MODEL,
        subcategory="physics",
        input_schema={
            "type": "object",
            "required": ["data", "physics_laws"],
            "properties": {
                "data": {"type": "array"},
                "physics_laws": {"type": "array", "description": "物理方程列表"}
            }
        },
        estimated_time=180,
        complexity=SkillComplexity.COMPLEX,
        requires_confirmation=True,
        requires_gpu=True
    )
    
    # ==================== 后处理类 ====================
    
    skills["postprocess_trajectory"] = SkillMetadata(
        skill_id="postprocess_trajectory",
        name="轨迹预测",
        description="使用训练好的模型进行轨迹预测",
        category=SkillCategory.POSTPROCESS,
        input_schema={
            "type": "object",
            "required": ["model", "initial_state", "horizon"],
            "properties": {
                "model": {"type": "object"},
                "initial_state": {"type": "array"},
                "horizon": {"type": "integer"}
            }
        },
        estimated_time=10,
        complexity=SkillComplexity.SIMPLE
    )
    
    skills["postprocess_confidence"] = SkillMetadata(
        skill_id="postprocess_confidence",
        name="不确定性量化",
        description="计算预测的置信区间",
        category=SkillCategory.POSTPROCESS,
        input_schema={
            "type": "object",
            "required": ["predictions"],
            "properties": {
                "predictions": {"type": "array"},
                "method": {"type": "string", "enum": ["bootstrap", "ensemble", "analytical"]}
            }
        },
        estimated_time=20,
        complexity=SkillComplexity.MODERATE
    )
    
    skills["postprocess_anomaly"] = SkillMetadata(
        skill_id="postprocess_anomaly",
        name="异常检测",
        description="基于预测残差检测异常",
        category=SkillCategory.POSTPROCESS,
        input_schema={
            "type": "object",
            "required": ["observed", "predicted"],
            "properties": {
                "observed": {"type": "array"},
                "predicted": {"type": "array"},
                "threshold": {"type": "number", "default": 3.0}
            }
        },
        estimated_time=5,
        complexity=SkillComplexity.SIMPLE
    )
    
    # ==================== 可视化类 ====================
    
    skills["viz_trajectory"] = SkillMetadata(
        skill_id="viz_trajectory",
        name="轨迹可视化",
        description="绘制预测轨迹与实际轨迹对比图",
        category=SkillCategory.VISUALIZATION,
        input_schema={
            "type": "object",
            "required": ["time", "actual", "predicted"],
            "properties": {
                "time": {"type": "array"},
                "actual": {"type": "array"},
                "predicted": {"type": "array"},
                "confidence": {"type": "array", "required": False}
            }
        },
        estimated_time=5,
        complexity=SkillComplexity.SIMPLE
    )
    
    skills["viz_phase"] = SkillMetadata(
        skill_id="viz_phase",
        name="相图可视化",
        description="绘制系统相图",
        category=SkillCategory.VISUALIZATION,
        input_schema={
            "type": "object",
            "required": ["state1", "state2"],
            "properties": {
                "state1": {"type": "array"},
                "state2": {"type": "array"},
                "labels": {"type": "array"}
            }
        },
        estimated_time=3,
        complexity=SkillComplexity.SIMPLE
    )
    
    skills["viz_heatmap"] = SkillMetadata(
        skill_id="viz_heatmap",
        name="热力图",
        description="绘制2D热力图展示不确定性",
        category=SkillCategory.VISUALIZATION,
        input_schema={
            "type": "object",
            "required": ["data"],
            "properties": {
                "data": {"type": "array"},
                "title": {"type": "string"}
            }
        },
        estimated_time=5,
        complexity=SkillComplexity.SIMPLE
    )
    
    return skills


def get_skills_by_category(category: SkillCategory) -> dict[str, SkillMetadata]:
    """按分类获取技能"""
    all_skills = get_atomic_skills_library()
    return {
        skill_id: meta
        for skill_id, meta in all_skills.items()
        if meta.category == category
    }


def get_skill_chain_recommendations(task_type: str) -> list[list[str]]:
    """
    获取技能链推荐
    
    Args:
        task_type: 任务类型 (forecast, anomaly_detection, etc.)
        
    Returns:
        推荐的技能链列表
    """
    from uap.skill.atomic_implemented import MODELING_ATOMIC_SKILL_IDS

    def _only_implemented(chain: list[str]) -> list[str]:
        return [s for s in chain if s in MODELING_ATOMIC_SKILL_IDS]

    recommendations = {
        "forecast": [
            _only_implemented(
                [
                    "data_load_csv",
                    "preprocess_missing",
                    "preprocess_normalize",
                    "feature_derivative",
                    "model_monte_carlo",
                ]
            ),
            _only_implemented(
                ["data_load_csv", "preprocess_missing", "model_monte_carlo"]
            ),
        ],
        "anomaly_detection": [
            _only_implemented(
                ["data_load_csv", "preprocess_missing", "preprocess_normalize", "feature_derivative"]
            ),
        ],
        "uncertainty_quantification": [
            _only_implemented(["data_load_csv", "model_monte_carlo"]),
        ],
        "modeling": [
            _only_implemented(
                [
                    "data_load_csv",
                    "preprocess_missing",
                    "preprocess_normalize",
                    "preprocess_resample",
                    "feature_derivative",
                ]
            ),
        ],
    }

    return [c for c in recommendations.get(task_type, []) if c]
