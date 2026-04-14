"""
UAP 技能系统 - 核心数据模型

定义技能会话追踪、操作节点、项目技能等核心数据结构。
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class ActionType(str, Enum):
    """操作类型枚举"""
    THOUGHT = "thought"              # 思考过程
    TOOL_CALL = "tool_call"         # 工具调用
    OBSERVATION = "observation"      # 观察结果
    USER_CORRECTION = "correction"   # 用户纠正
    FINAL_OUTPUT = "final_output"   # 最终输出


class SessionStatus(str, Enum):
    """会话状态枚举"""
    ACTIVE = "active"               # 进行中
    COMPLETED = "completed"         # 已完成
    ABORTED = "aborted"             # 已中止
    SKIPPED = "skipped"             # 已跳过


class SkillCategory(str, Enum):
    """技能类别枚举"""
    MODELING = "modeling"           # 建模技能
    PREDICTION = "prediction"        # 预测技能
    ANALYSIS = "analysis"           # 分析技能
    VISUALIZATION = "visualization" # 可视化技能
    GENERAL = "general"             # 通用技能


class ActionNode(BaseModel):
    """
    操作轨迹节点 - 技能生成的原子单位
    
    记录 Agent 执行过程中的每一步操作，包括思考、工具调用、观察结果等。
    """
    
    step_id: int = Field(..., description="步骤序号")
    type: ActionType = Field(..., description="操作类型")
    tool_name: Optional[str] = Field(None, description="工具名称")
    
    # 输入输出
    input_params: dict = Field(default_factory=dict, description="输入参数（脱敏后）")
    output_summary: str = Field("", description="输出摘要（截断处理，防溢出）")
    
    # 执行信息
    duration_ms: int = Field(0, description="执行耗时（毫秒）")
    is_error: bool = Field(False, description="是否出错")
    error_recovery: Optional[str] = Field(None, description="错误恢复策略")
    
    # 额外上下文
    metadata: dict = Field(default_factory=dict, description="额外元数据")
    
    class Config:
        use_enum_values = True


class SkillSession(BaseModel):
    """
    技能生成会话 - DST (Dialogue State Tracking) 状态追踪
    
    在内存中维护 SkillSession 对象，实时记录 Agent 的思考-行动-观察循环。
    当会话结束时，根据触发条件评估是否值得生成技能。
    """
    
    session_id: str = Field(..., description="会话唯一ID")
    project_id: str = Field(..., description="所属项目ID")
    start_time: datetime = Field(default_factory=datetime.now, description="开始时间")
    end_time: Optional[datetime] = Field(None, description="结束时间")
    
    # DST 核心字段
    user_query: str = Field("", description="用户原始问题")
    intent: str = Field("general", description="识别的意图分类")
    actions: list[ActionNode] = Field(default_factory=list, description="操作轨迹列表")
    final_output: Any = Field(None, description="最终输出")
    
    # 元数据
    status: SessionStatus = Field(SessionStatus.ACTIVE, description="会话状态")
    corrections: int = Field(0, description="用户纠正次数")
    tool_call_count: int = Field(0, description="工具调用次数")
    total_duration_ms: int = Field(0, description="总耗时")
    tokens_used: int = Field(0, description="消耗的 token 数")
    
    class Config:
        use_enum_values = True
    
    def add_action(self, action: ActionNode) -> None:
        """添加操作节点"""
        self.actions.append(action)
        if action.type == ActionType.TOOL_CALL:
            self.tool_call_count += 1
        if action.type == ActionType.USER_CORRECTION:
            self.corrections += 1
    
    def get_trajectory_text(self) -> str:
        """获取操作轨迹文本（用于生成技能）"""
        lines = []
        for action in self.actions:
            if action.type in [ActionType.THOUGHT, ActionType.TOOL_CALL]:
                lines.append(
                    f"Step {action.step_id}: [{action.type}] {action.tool_name or 'reasoning'}"
                )
                lines.append(f"  Input: {action.input_params}")
                lines.append(f"  Output: {action.output_summary[:200]}...")
        return "\n".join(lines)
    
    def should_generate_skill(self, threshold_config: dict = None) -> tuple[bool, str]:
        """
        评估是否应该生成技能
        
        Args:
            threshold_config: 阈值配置
            
        Returns:
            (should_generate, reason) 元组
        """
        config = threshold_config or {
            "min_steps": 5,
            "min_corrections": 0,
            "min_duration_ms": 30000,
            "min_confidence": 0.7
        }
        
        reasons = []
        
        # 复杂度达标
        if len(self.actions) >= config["min_steps"]:
            reasons.append(f"复杂度达标 ({len(self.actions)} >= {config['min_steps']})")
        
        # 用户纠正过 -> 说明有独特偏好，必须记录
        if self.corrections > config["min_corrections"]:
            reasons.append(f"用户纠正过 ({self.corrections} 次)")
        
        # 耗时达标
        if self.total_duration_ms >= config["min_duration_ms"]:
            reasons.append(f"耗时达标 ({self.total_duration_ms/1000:.1f}s)")
        
        # 检查是否有有效输出
        if self.final_output is not None and not self._has_critical_errors():
            reasons.append("成功完成任务")
        
        should_generate = len(reasons) >= 2
        
        return should_generate, "; ".join(reasons) if reasons else "未达到触发条件"
    
    def _has_critical_errors(self) -> bool:
        """检查是否有严重错误"""
        return any(a.is_error for a in self.actions[-3:])  # 最近3步有错误
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return self.model_dump()
    
    @classmethod
    def from_dict(cls, data: dict) -> "SkillSession":
        """从字典创建"""
        return cls(**data)


class SkillStep(BaseModel):
    """
    技能执行步骤
    
    定义技能的单个执行步骤，包括工具调用、Prompt 执行等。
    """
    
    step_number: int = Field(..., description="步骤序号")
    title: str = Field(..., description="步骤标题")
    description: str = Field("", description="详细描述")
    action_type: ActionType = Field(ActionType.TOOL_CALL, description="行动类型")
    
    # 行动细节
    tool_name: Optional[str] = Field(None, description="调用的工具")
    parameters: dict = Field(default_factory=dict, description="参数字典")
    prompt_template: Optional[str] = Field(None, description="Prompt 模板")
    
    # 条件分支
    conditions: list[str] = Field(default_factory=list, description="执行条件")
    alternatives: list[str] = Field(default_factory=list, description="备选方案")
    
    # 预期输出
    expected_output: str = Field("", description="预期输出描述")
    validation_rules: list[str] = Field(default_factory=list, description="验证规则")
    
    class Config:
        use_enum_values = True
    
    def render_prompt(self, context: dict) -> str:
        """渲染 Prompt 模板"""
        if not self.prompt_template:
            return ""
        
        template = self.prompt_template
        for key, value in context.items():
            placeholder = f"{{{{{key}}}}}"
            if placeholder in template:
                template = template.replace(placeholder, str(value))
        
        return template


class SkillParameter(BaseModel):
    """技能参数定义"""
    
    name: str = Field(..., description="参数名称")
    description: str = Field("", description="参数描述")
    type: str = Field("string", description="参数类型")
    required: bool = Field(True, description="是否必需")
    default: Optional[Any] = Field(None, description="默认值")
    options: list[str] = Field(default_factory=list, description="可选值列表")
    
    # 验证
    min_value: Optional[float] = Field(None, description="最小值")
    max_value: Optional[float] = Field(None, description="最大值")
    pattern: Optional[str] = Field(None, description="正则表达式")


class ProjectSkill(BaseModel):
    """
    项目专属技能 - 沉淀的知识资产
    
    每个项目可以有多个专属技能，这些技能可以是：
    - AI 自动从对话中生成
    - 用户手动创建
    - 从通用技能模板实例化
    """
    
    skill_id: str = Field(..., description="技能唯一ID")
    project_id: str = Field(..., description="所属项目ID")
    
    # 技能元信息
    name: str = Field(..., description="技能名称")
    description: str = Field("", description="一句话描述")
    category: SkillCategory = Field(SkillCategory.GENERAL, description="技能类别")
    trigger_conditions: list[str] = Field(default_factory=list, description="触发条件列表")
    
    # 技能内容
    skill_content: str = Field("", description="技能完整描述 (Markdown)")
    steps: list[SkillStep] = Field(default_factory=list, description="执行步骤")
    parameters: list[SkillParameter] = Field(default_factory=list, description="参数定义")
    
    # 前置条件
    preconditions: list[str] = Field(default_factory=list, description="前置条件")
    postconditions: list[str] = Field(default_factory=list, description="后置条件")
    
    # 质量指标
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="置信度 0-1")
    usage_count: int = Field(0, description="使用次数")
    success_count: int = Field(0, description="成功次数")
    success_rate: float = Field(0.0, description="成功率")
    
    # 版本信息
    source_session_id: Optional[str] = Field(None, description="来源会话ID")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")
    version: int = Field(1, description="版本号")
    is_auto_generated: bool = Field(True, description="是否AI自动生成")
    parent_skill_id: Optional[str] = Field(None, description="父技能ID（用于技能继承）")
    
    class Config:
        use_enum_values = True
    
    def record_usage(self, success: bool) -> None:
        """记录一次使用"""
        self.usage_count += 1
        if success:
            self.success_count += 1
        self.success_rate = (
            self.success_count / self.usage_count 
            if self.usage_count > 0 else 0.0
        )
        self.updated_at = datetime.now()
    
    def increment_version(self) -> None:
        """递增版本号"""
        self.version += 1
        self.updated_at = datetime.now()
    
    def to_skill_md(self) -> str:
        """转换为 SKILL.md 格式"""
        front_matter = f"""---
skill_id: {self.skill_id}
project_id: {self.project_id}
name: {self.name}
description: {self.description}
category: {self.category}
version: {self.version}
confidence: {self.confidence:.2f}
trigger_conditions:
{chr(10).join(f'  - {tc}' for tc in self.trigger_conditions)}
created_at: {self.created_at.isoformat()}
created_by: {"auto_generated" if self.is_auto_generated else "manual"}
---

"""
        
        content = f"""# {self.name}

{self.description}

## 触发条件

{chr(10).join(f'- {tc}' for tc in self.trigger_conditions)}

## 前置条件

{chr(10).join(f'- {pc}' for pc in self.preconditions) if self.preconditions else '无'}

## 执行步骤

"""
        
        for i, step in enumerate(self.steps, 1):
            content += f"""### {i}. {step.title}

{step.description}

"""
            if step.tool_name:
                content += f"**工具**: `{step.tool_name}`\n\n"
            if step.prompt_template:
                content += f"""**Prompt 模板**:
```
{step.prompt_template}
```

"""
        
        if self.parameters:
            content += """## 参数说明

| 参数 | 类型 | 必需 | 描述 |
|------|------|------|------|
"""
            for param in self.parameters:
                content += f"| {param.name} | {param.type} | {'是' if param.required else '否'} | {param.description} |\n"
        
        content += f"""

## 使用统计

- 使用次数: {self.usage_count}
- 成功次数: {self.success_count}
- 成功率: {self.success_rate:.1%}
- 置信度: {self.confidence:.1%}

"""
        
        return front_matter + content
    
    @classmethod
    def from_skill_md(cls, content: str, project_id: str) -> "ProjectSkill":
        """从 SKILL.md 格式解析"""
        import re
        import yaml
        
        # 解析 Front Matter
        front_matter_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        if front_matter_match:
            metadata = yaml.safe_load(front_matter_match.group(1))
        else:
            metadata = {}
        
        # 提取正文内容
        body = re.sub(r'^---\n.*?\n---\n?', '', content, flags=re.DOTALL)
        
        skill_id = metadata.get('skill_id', f"skill_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        
        return cls(
            skill_id=skill_id,
            project_id=project_id,
            name=metadata.get('name', '未命名技能'),
            description=metadata.get('description', ''),
            category=SkillCategory(metadata.get('category', 'general')),
            trigger_conditions=metadata.get('trigger_conditions', []),
            skill_content=body,
            confidence=metadata.get('confidence', 0.5),
            version=metadata.get('version', 1),
            is_auto_generated=metadata.get('created_by') == 'auto_generated',
            created_at=metadata.get('created_at', datetime.now()),
        )
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return self.model_dump()
    
    @classmethod
    def from_dict(cls, data: dict) -> "ProjectSkill":
        """从字典创建"""
        return cls(**data)


class SkillExecution(BaseModel):
    """技能执行记录"""
    
    execution_id: str = Field(..., description="执行ID")
    skill_id: str = Field(..., description="技能ID")
    project_id: str = Field(..., description="项目ID")
    
    start_time: datetime = Field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    
    status: str = Field("running", description="running/completed/failed")
    error: Optional[str] = None
    
    step_results: list[dict] = Field(default_factory=list, description="各步骤结果")
    final_result: Optional[Any] = Field(None, description="最终结果")
    
    parameters: dict = Field(default_factory=dict, description="执行参数")
    context: dict = Field(default_factory=dict, description="执行上下文")
    
    def complete(self, result: Any) -> None:
        """标记为完成"""
        self.status = "completed"
        self.final_result = result
        self.end_time = datetime.now()
    
    def fail(self, error: str) -> None:
        """标记为失败"""
        self.status = "failed"
        self.error = error
        self.end_time = datetime.now()
    
    @property
    def duration_ms(self) -> int:
        """执行耗时（毫秒）"""
        if self.end_time and self.start_time:
            return int((self.end_time - self.start_time).total_seconds() * 1000)
        return int((datetime.now() - self.start_time).total_seconds() * 1000)
