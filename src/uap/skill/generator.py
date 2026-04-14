"""
UAP 技能系统 - 技能生成器

基于 DST 追踪的操作轨迹，自动生成项目专属技能。
"""

import json
import re
import uuid
from datetime import datetime
from typing import Optional

from uap.skill.models import (
    ProjectSkill, SkillSession, SkillStep, SkillParameter,
    SkillCategory, ActionNode, ActionType
)
from uap.llm import OllamaClient


# ==================== Prompt 模板 ====================

SKILL_GENERATION_SYSTEM_PROMPT = """你是一个复杂系统建模和预测专家。你的任务是根据 Agent 执行日志，为 UAP 项目生成专业的技能文档。

## 输出要求
1. 生成标准 Markdown 格式的技能文档
2. 技能必须是可执行的，包含清晰的步骤
3. 使用中文输出
4. 技能应该专注于复杂系统建模或预测相关的任务

## 技能结构
每个技能必须包含:
- name: 简洁的技能名称（动词短语）
- description: 一句话描述
- trigger_conditions: 触发条件列表
- preconditions: 前置条件
- steps: 执行步骤列表
- parameters: 参数定义

## 质量标准
- 步骤必须清晰可执行
- 参数必须明确定义
- 考虑边界情况和错误处理"""


SKILL_GENERATION_USER_PROMPT = """## 项目信息
- 项目ID: {project_id}
- 项目名称: {project_name}
- 系统类型: {system_type}
- 领域: {domain}

## 执行轨迹
{action_trajectory}

## 用户原始问题
{user_query}

## 最终输出
{final_output}

请根据以上信息，生成一个专业的技能文档。输出 JSON 格式:

```json
{{
  "name": "技能名称",
  "description": "一句话描述",
  "category": "modeling/prediction/analysis/visualization",
  "trigger_conditions": ["触发条件1", "触发条件2"],
  "preconditions": ["前置条件1"],
  "steps": [
    {{
      "step_number": 1,
      "title": "步骤标题",
      "description": "步骤详细描述",
      "action_type": "tool_call/thought",
      "tool_name": "工具名或null",
      "prompt_template": "Prompt模板或null",
      "expected_output": "预期输出描述"
    }}
  ],
  "parameters": [
    {{
      "name": "参数名",
      "description": "参数描述",
      "type": "string/number/boolean",
      "required": true/false,
      "default": "默认值或null"
    }}
  ]
}}
```"""


SKILL_VALIDATION_PROMPT = """你是一个技能评估专家。请评估以下技能的完整性和可用性。

## 技能内容
{skill_content}

## 评估标准
1. 完整性: 是否包含所有必要字段
2. 可执行性: 步骤是否清晰可执行
3. 适用性: 是否适合复杂系统建模/预测场景
4. 改进建议: 如何优化

请输出 JSON 格式:
```json
{{
  "is_valid": true/false,
  "completeness_score": 0.0-1.0,
  "executability_score": 0.0-1.0,
  "relevance_score": 0.0-1.0,
  "issues": ["问题1", "问题2"],
  "suggestions": ["建议1"]
}}
```"""


class SkillGenerator:
    """
    技能生成器
    
    从 DST 追踪到的操作序列，生成标准格式的技能文档。
    """
    
    # 敏感关键词列表（用于脱敏）
    SENSITIVE_KEYWORDS = [
        "password", "token", "api_key", "secret", "apikey",
        "authorization", "cookie", "key", "credential"
    ]
    
    def __init__(self, llm_client: OllamaClient):
        """
        初始化技能生成器
        
        Args:
            llm_client: LLM 客户端，用于调用大模型生成技能
        """
        self.llm = llm_client
    
    def generate(
        self,
        session: SkillSession,
        project_info: dict
    ) -> Optional[ProjectSkill]:
        """
        从会话生成技能
        
        Args:
            session: DST 追踪的会话
            project_info: 项目信息
            
        Returns:
            生成的技能对象，生成失败返回 None
        """
        try:
            # 1. 过滤噪音节点
            clean_actions = self._filter_noise(session)
            
            # 2. 脱敏敏感参数
            sanitized_actions = [
                self._redact_sensitive(a) for a in clean_actions
            ]
            
            # 3. 构建生成 Prompt
            user_prompt = self._build_generation_prompt(
                session, project_info, sanitized_actions
            )
            
            # 4. 调用 LLM 生成技能内容
            response = self.llm.chat([
                {"role": "system", "content": SKILL_GENERATION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ])
            
            # 5. 解析 LLM 输出
            skill_data = self._parse_llm_response(response)
            
            if not skill_data:
                return None
            
            # 6. 创建技能对象
            skill = self._create_skill_object(skill_data, session)
            
            # 7. 验证技能质量
            if not self._validate_skill(skill):
                return None
            
            # 8. 计算置信度
            skill.confidence = self._calculate_confidence(session, skill)
            
            return skill
            
        except Exception as e:
            print(f"Skill generation failed: {e}")
            return None
    
    def _filter_noise(self, session: SkillSession) -> list[ActionNode]:
        """
        过滤噪音节点
        
        移除纯观察节点，只保留思考和工具调用。
        """
        return [
            a for a in session.actions
            if a.type in [ActionType.THOUGHT, ActionType.TOOL_CALL]
        ]
    
    def _redact_sensitive(self, action: ActionNode) -> ActionNode:
        """
        脱敏敏感参数
        
        将包含敏感关键词的参数值替换为占位符。
        """
        redacted_params = {}
        for key, value in action.input_params.items():
            if any(sensitive in key.lower() for sensitive in self.SENSITIVE_KEYWORDS):
                redacted_params[key] = "<SECRET>"
            else:
                redacted_params[key] = value
        
        action.input_params = redacted_params
        
        # 同时脱敏输出摘要
        if action.output_summary:
            for sensitive in self.SENSITIVE_KEYWORDS:
                pattern = rf"({sensitive}['\"]?\s*[:=]\s*)['\"]?[\w\-]+['\"]?"
                action.output_summary = re.sub(
                    pattern, r"\1<SECRET>", 
                    action.output_summary, 
                    flags=re.IGNORECASE
                )
        
        return action
    
    def _build_generation_prompt(
        self,
        session: SkillSession,
        project_info: dict,
        actions: list[ActionNode]
    ) -> str:
        """构建技能生成 Prompt"""
        # 构建轨迹文本
        trajectory_parts = []
        for action in actions:
            trajectory_parts.append(
                f"Step {action.step_id}: [{action.type}] {action.tool_name or 'reasoning'}"
            )
            trajectory_parts.append(f"  Input: {json.dumps(action.input_params, ensure_ascii=False)}")
            trajectory_parts.append(f"  Output: {action.output_summary[:500]}")
        
        trajectory_text = "\n".join(trajectory_parts)
        
        # 获取最终输出
        final_output = ""
        if session.final_output:
            if isinstance(session.final_output, str):
                final_output = session.final_output[:1000]
            else:
                final_output = json.dumps(session.final_output, ensure_ascii=False)[:1000]
        
        return SKILL_GENERATION_USER_PROMPT.format(
            project_id=project_info.get("project_id", ""),
            project_name=project_info.get("name", "未命名项目"),
            system_type=project_info.get("system_type", "复杂系统"),
            domain=project_info.get("domain", "通用领域"),
            action_trajectory=trajectory_text,
            user_query=session.user_query,
            final_output=final_output
        )
    
    def _parse_llm_response(self, response: str) -> Optional[dict]:
        """
        解析 LLM 响应
        
        从 LLM 输出中提取 JSON 格式的技能数据。
        """
        if not response:
            return None
        
        # 尝试提取 JSON 代码块
        json_match = re.search(
            r'```json\s*(.*?)\s*```',
            response,
            re.DOTALL
        )
        
        if json_match:
            json_str = json_match.group(1)
        else:
            # 尝试直接解析整个响应
            json_str = response
        
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            # 尝试提取 JSON 对象
            obj_match = re.search(r'\{.*\}', json_str, re.DOTALL)
            if obj_match:
                try:
                    return json.loads(obj_match.group())
                except json.JSONDecodeError:
                    pass
        
        return None
    
    def _create_skill_object(
        self,
        skill_data: dict,
        session: SkillSession
    ) -> ProjectSkill:
        """从技能数据创建技能对象"""
        # 生成技能 ID
        skill_id = f"skill_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 构建步骤
        steps = []
        for step_data in skill_data.get("steps", []):
            step = SkillStep(
                step_number=step_data.get("step_number", len(steps) + 1),
                title=step_data.get("title", f"步骤 {len(steps) + 1}"),
                description=step_data.get("description", ""),
                action_type=ActionType(step_data.get("action_type", "tool_call")),
                tool_name=step_data.get("tool_name"),
                prompt_template=step_data.get("prompt_template"),
                expected_output=step_data.get("expected_output", "")
            )
            steps.append(step)
        
        # 构建参数
        parameters = []
        for param_data in skill_data.get("parameters", []):
            param = SkillParameter(
                name=param_data.get("name", ""),
                description=param_data.get("description", ""),
                type=param_data.get("type", "string"),
                required=param_data.get("required", True),
                default=param_data.get("default")
            )
            parameters.append(param)
        
        # 确定类别
        category_str = skill_data.get("category", "general")
        try:
            category = SkillCategory(category_str)
        except ValueError:
            category = SkillCategory.GENERAL
        
        return ProjectSkill(
            skill_id=skill_id,
            project_id=session.project_id,
            name=skill_data.get("name", "未命名技能"),
            description=skill_data.get("description", ""),
            category=category,
            trigger_conditions=skill_data.get("trigger_conditions", []),
            preconditions=skill_data.get("preconditions", []),
            steps=steps,
            parameters=parameters,
            source_session_id=session.session_id,
            is_auto_generated=True
        )
    
    def _validate_skill(self, skill: ProjectSkill) -> bool:
        """
        验证技能质量
        
        检查技能是否满足最低质量标准。
        """
        # 名称不能为空
        if not skill.name or skill.name == "未命名技能":
            return False
        
        # 必须有至少一个步骤
        if not skill.steps:
            return False
        
        # 步骤必须有标题
        for step in skill.steps:
            if not step.title:
                step.title = f"步骤 {step.step_number}"
        
        return True
    
    def _calculate_confidence(
        self,
        session: SkillSession,
        skill: ProjectSkill
    ) -> float:
        """
        计算技能置信度
        
        基于会话元数据和质量指标综合计算。
        """
        score = 0.4  # 基础分
        
        # 用户纠正过 -> 说明有价值
        if session.corrections > 0:
            score += 0.15
        
        # 没有错误
        has_error = any(a.is_error for a in session.actions)
        if not has_error:
            score += 0.15
        
        # 步骤数适中 (3-8步)
        if 3 <= len(skill.steps) <= 8:
            score += 0.1
        
        # 步骤有详细描述
        described_steps = sum(1 for s in skill.steps if s.description)
        if described_steps / len(skill.steps) > 0.7:
            score += 0.1
        
        # 触发条件明确
        if len(skill.trigger_conditions) >= 2:
            score += 0.1
        
        return min(score, 1.0)
    
    def validate_existing_skill(self, skill: ProjectSkill) -> dict:
        """
        验证现有技能
        
        返回验证结果和改进建议。
        """
        response = self.llm.chat([
            {"role": "system", "content": "你是一个技能评估专家。"},
            {"role": "user", "content": SKILL_VALIDATION_PROMPT.format(
                skill_content=skill.to_skill_md()
            )}
        ])
        
        try:
            return self._parse_llm_response(response) or {}
        except Exception:
            return {"is_valid": False, "error": "Validation failed"}


class SkillTemplateGenerator:
    """
    技能模板生成器
    
    从通用模板生成特定领域的技能实例。
    """
    
    def __init__(self, llm_client: OllamaClient):
        self.llm = llm_client
    
    def generate_from_template(
        self,
        template_name: str,
        project_info: dict,
        customizations: dict = None
    ) -> ProjectSkill:
        """
        从模板生成技能
        
        Args:
            template_name: 模板名称
            project_info: 项目信息
            customizations: 自定义配置
        """
        # 预定义模板
        templates = {
            "lotka_volterra_modeling": self._lotka_volterra_template,
            "sir_epidemic_modeling": self._sir_modeling_template,
            "prey_predator_forecast": self._prey_predator_forecast_template,
            "chaos_detection": self._chaos_detection_template,
            "stability_analysis": self._stability_analysis_template,
        }
        
        template_func = templates.get(template_name)
        if not template_func:
            raise ValueError(f"Unknown template: {template_name}")
        
        skill = template_func(project_info, customizations)
        
        # 生成唯一 ID
        skill.skill_id = f"skill_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        skill.is_auto_generated = False
        
        return skill
    
    def _lotka_volterra_template(
        self,
        project_info: dict,
        customizations: dict
    ) -> ProjectSkill:
        """Lotka-Volterra 捕食者-猎物建模模板"""
        return ProjectSkill(
            skill_id="",
            project_id=project_info.get("project_id", ""),
            name="Lotka-Volterra 生态系统建模",
            description="建立捕食者-猎物系统的微分方程模型",
            category=SkillCategory.MODELING,
            trigger_conditions=[
                "建立捕食者猎物模型",
                "生态系统动态建模",
                "分析物种数量变化"
            ],
            preconditions=[
                "已知捕食者和猎物的初始数量",
                "了解种间关系"
            ],
            steps=[
                SkillStep(
                    step_number=1,
                    title="定义系统变量",
                    description="识别并定义系统中的状态变量",
                    action_type=ActionType.THOUGHT,
                    expected_output="变量列表 (x: 猎物数量, y: 捕食者数量)"
                ),
                SkillStep(
                    step_number=2,
                    title="建立微分方程",
                    description="基于 Lotka-Volterra 方程建立模型",
                    action_type=ActionType.TOOL_CALL,
                    tool_name="equation_builder",
                    prompt_template="建立 Lotka-Volterra 方程:\n"
                                   "dx/dt = αx - βxy (猎物增长 - 被捕食)\n"
                                   "dy/dt = δxy - γy (捕食者增长 - 死亡)\n"
                                   "其中 α, β, γ, δ 为参数",
                    expected_output="完整的微分方程组"
                ),
                SkillStep(
                    step_number=3,
                    title="参数估计",
                    description="从历史数据估计模型参数",
                    action_type=ActionType.TOOL_CALL,
                    tool_name="parameter_fitter",
                    expected_output="参数值: α, β, γ, δ"
                ),
                SkillStep(
                    step_number=4,
                    title="模型验证",
                    description="验证模型与实际数据的拟合度",
                    action_type=ActionType.TOOL_CALL,
                    tool_name="model_validator",
                    expected_output="R² 值和残差分析"
                )
            ],
            parameters=[
                SkillParameter(name="α", description="猎物自然增长率", type="number", required=True),
                SkillParameter(name="β", description="被捕食率", type="number", required=True),
                SkillParameter(name="γ", description="捕食者死亡率", type="number", required=True),
                SkillParameter(name="δ", description="捕食者转化效率", type="number", required=True),
            ]
        )
    
    def _sir_modeling_template(
        self,
        project_info: dict,
        customizations: dict
    ) -> ProjectSkill:
        """SIR 传染病建模模板"""
        return ProjectSkill(
            skill_id="",
            project_id=project_info.get("project_id", ""),
            name="SIR 传染病传播建模",
            description="建立传染病 SIR 模型预测疫情传播",
            category=SkillCategory.MODELING,
            trigger_conditions=[
                "传染病建模",
                "疫情预测",
                "传播动力学分析"
            ],
            steps=[
                SkillStep(
                    step_number=1,
                    title="定义隔室",
                    description="定义 S(易感)、I(感染)、R(康复) 三个隔室",
                    action_type=ActionType.THOUGHT,
                    expected_output="S, I, R 定义"
                ),
                SkillStep(
                    step_number=2,
                    title="建立方程",
                    description="建立 SIR 微分方程",
                    action_type=ActionType.TOOL_CALL,
                    tool_name="equation_builder",
                    prompt_template="建立 SIR 方程:\n"
                                   "dS/dt = -βSI/N\n"
                                   "dI/dt = βSI/N - γI\n"
                                   "dR/dt = γI",
                    expected_output="完整的 SIR 方程组"
                ),
                SkillStep(
                    step_number=3,
                    title="计算基本再生数",
                    description="计算 R₀ = β/γ",
                    action_type=ActionType.TOOL_CALL,
                    tool_name="calculator",
                    expected_output="R₀ 值及其意义"
                )
            ],
            parameters=[
                SkillParameter(name="β", description="传染率", type="number", required=True),
                SkillParameter(name="γ", description="康复率", type="number", required=True),
                SkillParameter(name="N", description="总人口", type="number", required=True),
            ]
        )
    
    def _prey_predator_forecast_template(
        self,
        project_info: dict,
        customizations: dict
    ) -> ProjectSkill:
        """捕食者-猎物预测模板"""
        return ProjectSkill(
            skill_id="",
            project_id=project_info.get("project_id", ""),
            name="捕食者-猎物动态预测",
            description="基于历史数据预测未来种群动态",
            category=SkillCategory.PREDICTION,
            trigger_conditions=[
                "预测种群数量",
                "未来动态预测",
                "周期性分析"
            ],
            steps=[
                SkillStep(
                    step_number=1,
                    title="准备历史数据",
                    description="整理历史种群数据",
                    action_type=ActionType.TOOL_CALL,
                    tool_name="data_loader",
                    expected_output="清洗后的时间序列数据"
                ),
                SkillStep(
                    step_number=2,
                    title="拟合 Lotka-Volterra 模型",
                    description="用历史数据估计参数",
                    action_type=ActionType.TOOL_CALL,
                    tool_name="koopman_predictor",
                    expected_output="拟合参数和误差"
                ),
                SkillStep(
                    step_number=3,
                    title="生成预测轨迹",
                    description="预测未来状态",
                    action_type=ActionType.TOOL_CALL,
                    tool_name="monte_carlo_predictor",
                    expected_output="预测区间和轨迹"
                )
            ],
            parameters=[
                SkillParameter(name="horizon_days", description="预测天数", type="number", 
                             required=True, default=30),
                SkillParameter(name="n_simulations", description="模拟次数", type="number",
                             required=False, default=100),
            ]
        )
    
    def _chaos_detection_template(
        self,
        project_info: dict,
        customizations: dict
    ) -> ProjectSkill:
        """混沌检测模板"""
        return ProjectSkill(
            skill_id="",
            project_id=project_info.get("project_id", ""),
            name="混沌检测与分岔分析",
            description="检测系统混沌特性并进行分岔分析",
            category=SkillCategory.ANALYSIS,
            trigger_conditions=[
                "检测混沌",
                "分岔分析",
                "李雅普诺夫指数"
            ],
            steps=[
                SkillStep(
                    step_number=1,
                    title="计算李雅普诺夫指数",
                    description="评估系统混沌程度",
                    action_type=ActionType.TOOL_CALL,
                    tool_name="lyapunov_analyzer",
                    expected_output="最大李雅普诺夫指数"
                ),
                SkillStep(
                    step_number=2,
                    title="庞加莱截面分析",
                    description="分析相空间结构",
                    action_type=ActionType.TOOL_CALL,
                    tool_name="poincare_section",
                    expected_output="截面图"
                )
            ],
            parameters=[
                SkillParameter(name="embedding_dim", description="嵌入维数", type="number",
                             required=False, default=3),
            ]
        )
    
    def _stability_analysis_template(
        self,
        project_info: dict,
        customizations: dict
    ) -> ProjectSkill:
        """稳定性分析模板"""
        return ProjectSkill(
            skill_id="",
            project_id=project_info.get("project_id", ""),
            name="系统稳定性分析",
            description="分析平衡点的稳定性",
            category=SkillCategory.ANALYSIS,
            trigger_conditions=[
                "稳定性分析",
                "平衡点分析",
                "系统收敛性"
            ],
            steps=[
                SkillStep(
                    step_number=1,
                    title="求平衡点",
                    description="求解系统方程的平衡点",
                    action_type=ActionType.TOOL_CALL,
                    tool_name="equation_solver",
                    expected_output="平衡点列表"
                ),
                SkillStep(
                    step_number=2,
                    title="线性化分析",
                    description="计算雅可比矩阵分析稳定性",
                    action_type=ActionType.TOOL_CALL,
                    tool_name="jacobian_analyzer",
                    expected_output="稳定性判断"
                )
            ]
        )
