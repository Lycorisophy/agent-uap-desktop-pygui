"""
技能执行器子系统 —— **Workflow 式行动**的高层封装（与 ReAct 并行存在）
======================================================================

- ``ModelingSkillExecutor``：面向「已注册 ProjectSkill」的建模链，内部仍可能调 LLM。
- ``PredictionSkillExecutor``：把预测引擎包成可编排步骤（见文件后部）。

与 **八大行动模式**：此处更接近「固定技能链 + LLM 子步」，而非 ReAct 的自由工具循环。
与 **Harness**：由 ``ProjectService`` 或其它服务在需要「重技能」路径时选择性调用。
======================================================================
"""

from typing import Any, Optional
from datetime import datetime

from uap.core.skills.models import (
    ProjectSkill, SkillCategory, SkillExecution,
    ActionType
)
from uap.core.skills.manager import SkillManager
from uap.core.skills.generator import SkillGenerator
from uap.prompts import PromptId, render


class ModelingSkillExecutor:
    """
    **建模类 ProjectSkill** 的执行入口：选技能 → 组装 ``context`` → ``execute_skill``。

    当不存在可用技能时，回退到 ``ModelExtractor``（**提示词工程的另一条管线**）。
    """

    def __init__(
        self,
        skill_manager: SkillManager,
        model_extractor
    ):
        """
        Args:
            skill_manager: 带存储的技能管理器
            model_extractor: JSON 契约式抽取器，作为通用回退
        """
        self.skills = skill_manager  # 工具编排与持久化
        self.extractor = model_extractor  # LLM 结构化抽取 **备用路径**
    
    def execute_modeling_skill(
        self,
        project_id: str,
        user_intent: str,
        conversation: list[dict],
        skill_id: Optional[str] = None
    ) -> dict:
        """
        执行建模技能
        
        Args:
            project_id: 项目ID
            user_intent: 用户意图描述
            conversation: 对话历史
            skill_id: 可选，指定技能ID
            
        Returns:
            执行结果字典
        """
        # 1. 获取技能
        if skill_id:
            skill = self.skills.get_skill(project_id, skill_id)
        else:
            # 选择最佳技能
            skill = self.skills.get_best_skill_for_task(
                project_id,
                user_intent,
                SkillCategory.MODELING
            )
        
        # 2. 如果没有找到技能，回退到通用提取
        if not skill:
            return self._fallback_to_generic_extraction(conversation, user_intent)
        
        # 3. 准备上下文
        context = {
            "project_id": project_id,
            "conversation": conversation,
            "user_intent": user_intent,
            "skill": skill
        }
        
        # 4. 执行技能
        execution = self.skills.execute_skill(
            skill,
            parameters={
                "conversation": conversation,
                "user_intent": user_intent
            },
            context=context
        )
        
        # 5. 处理结果
        return self._process_modeling_result(execution, skill)
    
    def _fallback_to_generic_extraction(
        self,
        conversation: list[dict],
        user_intent: str
    ) -> dict:
        """回退到通用模型提取"""
        result = self.extractor.extract_from_conversation(
            conversation,
            user_intent
        )
        
        return {
            "success": True,
            "fallback": True,
            "skill_used": None,
            "model": result
        }
    
    def _process_modeling_result(
        self,
        execution: SkillExecution,
        skill: ProjectSkill
    ) -> dict:
        """处理建模结果"""
        if execution.status == "completed":
            # 从步骤结果提取模型信息
            final_result = execution.final_result
            
            return {
                "success": True,
                "fallback": False,
                "skill_used": skill.skill_id,
                "skill_name": skill.name,
                "model": final_result.get("model") if isinstance(final_result, dict) else final_result,
                "execution": {
                    "duration_ms": execution.duration_ms,
                    "steps_completed": len(execution.step_results)
                }
            }
        else:
            return {
                "success": False,
                "fallback": True,
                "skill_used": skill.skill_id,
                "error": execution.error,
                "model": None
            }
    
    def extract_with_skill_guidance(
        self,
        project_id: str,
        conversation: list[dict],
        user_intent: str
    ) -> dict:
        """
        使用技能指导的模型提取
        
        结合技能最佳实践和通用提取。
        """
        # 获取相关技能
        relevant_skills = self.skills.get_relevant_skills(project_id, user_intent)
        modeling_skills = [
            s for s in relevant_skills 
            if s.category == SkillCategory.MODELING
        ]
        
        if not modeling_skills:
            # 无相关技能，直接提取
            result = self.extractor.extract_from_conversation(
                conversation, user_intent
            )
            return {
                "model": result,
                "skills_used": []
            }
        
        # 使用最高置信度的技能
        best_skill = modeling_skills[0]
        
        # 根据技能的 Prompt 模板构建提取提示
        steps_content = []
        for step in best_skill.steps:
            if step.prompt_template:
                steps_content.append(f"## {step.title}\n{step.prompt_template}")
        
        guidance_prompt = render(
            PromptId.SKILL_EXECUTOR_GUIDANCE,
            skill_name=best_skill.name,
            skill_description=best_skill.description,
            steps_block=chr(10).join(steps_content),
            user_intent=user_intent,
        )
        
        # 调用提取器
        result = self.extractor.extract_from_conversation(
            conversation,
            guidance_prompt
        )
        
        return {
            "model": result,
            "skills_used": [best_skill.skill_id],
            "skill_guidance": best_skill.name
        }


class PredictionSkillExecutor:
    """
    预测技能执行器
    
    专门执行预测类技能，集成 PredictionEngine。
    """
    
    def __init__(
        self,
        skill_manager: SkillManager,
        prediction_engine
    ):
        """
        初始化预测技能执行器
        
        Args:
            skill_manager: 技能管理器
            prediction_engine: 预测引擎
        """
        self.skills = skill_manager
        self.engine = prediction_engine
    
    def execute_prediction_skill(
        self,
        project,
        skill_id: Optional[str] = None,
        parameters: dict = None
    ) -> dict:
        """
        执行预测技能
        
        Args:
            project: 项目对象
            skill_id: 可选，指定技能ID
            parameters: 预测参数
            
        Returns:
            执行结果字典
        """
        parameters = parameters or {}
        
        # 1. 获取技能
        if skill_id:
            skill = self.skills.get_skill(project.id, skill_id)
        else:
            # 选择最佳预测技能
            skill = self.skills.get_best_skill_for_task(
                project.id,
                "预测",
                SkillCategory.PREDICTION
            )
        
        # 2. 如果没有找到技能，回退到默认预测
        if not skill:
            return self._fallback_to_default_prediction(project, parameters)
        
        # 3. 准备初始状态
        initial_state = self._prepare_initial_state(project, skill, parameters)
        
        # 4. 执行技能
        context = {
            "project": project,
            "initial_state": initial_state,
            "skill": skill
        }
        
        execution = self.skills.execute_skill(
            skill,
            parameters={
                **parameters,
                "initial_state": initial_state
            },
            context=context
        )
        
        # 5. 处理结果
        return self._process_prediction_result(execution, skill, project)
    
    def _fallback_to_default_prediction(
        self,
        project,
        parameters: dict
    ) -> dict:
        """回退到默认预测"""
        result = self.engine.predict(
            project,
            config=parameters
        )
        
        return {
            "success": True,
            "fallback": True,
            "skill_used": None,
            "prediction": result
        }
    
    def _prepare_initial_state(
        self,
        project,
        skill: ProjectSkill,
        parameters: dict
    ) -> dict:
        """准备初始状态"""
        # 尝试从技能参数中获取
        initial_state = {}
        
        # 从上下文参数获取
        if "initial_state" in parameters:
            initial_state = parameters["initial_state"]
        
        # 从项目模型获取默认值
        if not initial_state and project.system_model:
            for var in project.system_model.variables:
                if var.default_value is not None:
                    initial_state[var.name] = var.default_value
        
        return initial_state
    
    def _process_prediction_result(
        self,
        execution: SkillExecution,
        skill: ProjectSkill,
        project
    ) -> dict:
        """处理预测结果"""
        if execution.status == "completed":
            return {
                "success": True,
                "fallback": False,
                "skill_used": skill.skill_id,
                "skill_name": skill.name,
                "prediction": execution.final_result,
                "execution": {
                    "duration_ms": execution.duration_ms,
                    "steps_completed": len(execution.step_results)
                }
            }
        else:
            return {
                "success": False,
                "fallback": True,
                "skill_used": skill.skill_id,
                "error": execution.error,
                "prediction": None
            }
    
    def run_with_skill_pipeline(
        self,
        project,
        skill_id: str,
        additional_steps: list[dict] = None
    ) -> dict:
        """
        使用技能定义的自定义管道运行预测
        
        Args:
            project: 项目对象
            skill_id: 技能ID
            additional_steps: 额外的步骤
            
        Returns:
            预测结果
        """
        skill = self.skills.get_skill(project.id, skill_id)
        
        if not skill:
            return {"error": f"Skill not found: {skill_id}"}
        
        # 准备参数
        params = {
            "project_id": project.id,
            "model": project.system_model,
            "horizon_sec": 259200,  # 默认3天
            "frequency_sec": 3600   # 默认1小时
        }
        
        # 执行技能
        execution = self.skills.execute_skill(
            skill,
            parameters=params,
            context={"project": project}
        )
        
        # 添加额外步骤
        if additional_steps:
            for step in additional_steps:
                execution.step_results.append(step)
        
        return {
            "success": execution.status == "completed",
            "execution": execution,
            "skill": skill
        }


class SkillSessionTracker:
    """
    技能会话追踪器
    
    在对话过程中追踪 Agent 的操作，自动生成技能。
    """
    
    def __init__(self, skill_manager: SkillManager):
        self.skills = skill_manager
        self.current_session = None
    
    def start_tracking(
        self,
        project_id: str,
        user_query: str
    ) -> None:
        """开始追踪"""
        self.current_session = self.skills.start_session(
            project_id,
            user_query
        )
    
    def record_action(
        self,
        action_type: str,
        tool_name: str = None,
        input_params: dict = None,
        output_summary: str = "",
        duration_ms: int = 0,
        is_error: bool = False
    ) -> None:
        """记录操作"""
        if not self.current_session:
            return
        
        action = ActionNode(
            step_id=len(self.current_session.actions) + 1,
            type=ActionType(action_type),
            tool_name=tool_name,
            input_params=input_params or {},
            output_summary=output_summary,
            duration_ms=duration_ms,
            is_error=is_error
        )
        
        self.skills.record_action(self.current_session, action)
    
    def record_thought(self, thought: str) -> None:
        """记录思考"""
        self.record_action(
            action_type="thought",
            output_summary=thought
        )
    
    def record_tool_call(
        self,
        tool_name: str,
        input_params: dict,
        output_summary: str = "",
        duration_ms: int = 0,
        is_error: bool = False
    ) -> None:
        """记录工具调用"""
        self.record_action(
            action_type="tool_call",
            tool_name=tool_name,
            input_params=input_params,
            output_summary=output_summary,
            duration_ms=duration_ms,
            is_error=is_error
        )
    
    def record_correction(self, correction: str) -> None:
        """记录用户纠正"""
        self.record_action(
            action_type="correction",
            output_summary=correction
        )
    
    def complete_tracking(
        self,
        final_output: Any = None,
        project_info: dict = None
    ) -> Optional[ProjectSkill]:
        """
        完成追踪并尝试生成技能
        
        Returns:
            生成的技能，如果未达到触发条件则返回 None
        """
        if not self.current_session:
            return None
        
        self.skills.complete_session(
            self.current_session,
            final_output
        )
        
        # 检查是否应该生成技能
        should_gen, reason = self.skills.should_generate_skill(
            self.current_session
        )
        
        if should_gen:
            skill = self.skills.create_skill(
                self.current_session,
                project_info or {}
            )
            
            self.current_session = None
            return skill
        
        self.current_session = None
        return None
    
    def abort_tracking(self) -> None:
        """中止追踪"""
        if self.current_session:
            self.skills.abort_session(self.current_session)
            self.current_session = None
    
    @property
    def is_tracking(self) -> bool:
        """是否正在追踪"""
        return self.current_session is not None
    
    @property
    def session_id(self) -> Optional[str]:
        """当前会话ID"""
        return self.current_session.session_id if self.current_session else None
