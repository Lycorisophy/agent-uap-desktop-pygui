"""
UAP ReAct Agent - 思考行动模式引擎

基于"思考→行动→观察"循环的智能体实现。
让LLM决定使用哪些技能，通过DST跟踪建模进度。
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

from uap.skill.models import (
    ActionNode,
    ActionType,
    SessionStatus,
    SkillSession,
)
from uap.skill.atomic_skills import AtomicSkill, get_atomic_skills_library

_LOG = logging.getLogger("uap.react")


class ReactStep(BaseModel):
    """ReAct单步执行结果"""
    step_id: int
    thought: str = Field("", description="思考过程")
    action: str = Field("", description="选择的技能/动作")
    action_input: dict = Field(default_factory=dict, description="技能输入参数")
    observation: str = Field("", description="执行观察结果")
    is_error: bool = False
    error_message: Optional[str] = None
    duration_ms: int = 0


class ReactResult(BaseModel):
    """ReAct执行结果"""
    success: bool
    session_id: str
    steps: list[ReactStep] = Field(default_factory=list)
    final_output: Any = None
    error_message: Optional[str] = None
    total_steps: int = 0
    total_duration_ms: int = 0
    tool_calls: int = 0
    dst_state: dict = Field(default_factory=dict, description="DST状态快照")


class ReactAgent:
    """
    ReAct思考行动模式Agent

    核心流程:
    1. LLM思考决定下一步行动
    2. 选择并执行技能
    3. 观察执行结果
    4. 判断是否完成或继续循环
    """

    def __init__(
        self,
        llm_client,
        skills_registry: dict[str, AtomicSkill],
        dst_manager,
        max_iterations: int = 10,
        max_time_seconds: float = 120.0,
    ):
        """
        初始化ReAct Agent

        Args:
            llm_client: LLM客户端
            skills_registry: 技能注册表 {skill_id: AtomicSkill}
            dst_manager: DST对话状态管理器
            max_iterations: 最大迭代次数
            max_time_seconds: 最大执行时间
        """
        self.llm = llm_client
        self.skills = skills_registry
        self.dst = dst_manager
        self.max_iterations = max_iterations
        self.max_time = max_time_seconds

        _LOG.info("[ReActAgent] Initialized with %d skills", len(skills_registry))

    def run(self, task: str, context: dict = None) -> ReactResult:
        """
        执行ReAct循环

        Args:
            task: 用户任务描述
            context: 额外上下文

        Returns:
            ReactResult: 执行结果
        """
        session_id = str(uuid.uuid4())
        start_time = time.perf_counter()
        context = context or {}

        _LOG.info("[ReActAgent] Starting session: %s, task: %s", session_id, task[:100])

        # 初始化DST会话
        dst_session = self.dst.create_session(session_id, task, context)

        steps = []
        total_tool_calls = 0
        current_context = self._build_context(task, context, dst_session)

        for iteration in range(self.max_iterations):
            step_start = time.perf_counter()

            # 检查超时
            elapsed = time.perf_counter() - start_time
            if elapsed > self.max_time:
                _LOG.warning("[ReActAgent] Session %s timed out after %.1fs", session_id, elapsed)
                break

            step_id = iteration + 1
            _LOG.info("[ReActAgent] Step %d/%d", step_id, self.max_iterations)

            try:
                # 1. LLM思考决定行动
                thought_result = self._llm_think(current_context, steps)
                thought = thought_result.get("thought", "")
                action = thought_result.get("action", "")
                action_input = thought_result.get("action_input", {})

                _LOG.debug("[ReActAgent] Step %d: thought=%s, action=%s", step_id, thought[:50], action)

                # 2. 检查是否完成
                if action == "FINAL_ANSWER" or action == "":
                    final_output = thought_result.get("final_answer", "")
                    step = ReactStep(
                        step_id=step_id,
                        thought=thought,
                        action="FINAL_ANSWER",
                        observation="任务完成",
                        duration_ms=int((time.perf_counter() - step_start) * 1000)
                    )
                    steps.append(step)
                    break

                # 3. 执行技能
                obs, is_error, error_msg = self._execute_skill(action, action_input)

                if is_error:
                    _LOG.warning("[ReActAgent] Skill %s failed: %s", action, error_msg)

                # 4. 记录观察结果
                step = ReactStep(
                    step_id=step_id,
                    thought=thought,
                    action=action,
                    action_input=action_input,
                    observation=obs[:500] if obs else "",
                    is_error=is_error,
                    error_message=error_msg,
                    duration_ms=int((time.perf_counter() - step_start) * 1000)
                )
                steps.append(step)
                total_tool_calls += 1

                # 5. 更新DST状态
                self.dst.add_action(
                    session_id,
                    ActionNode(
                        step_id=step_id,
                        type=ActionType.TOOL_CALL if not is_error else ActionType.OBSERVATION,
                        tool_name=action,
                        input_params=action_input,
                        output_summary=obs[:200] if obs else "",
                        is_error=is_error
                    )
                )

                # 6. 更新上下文
                current_context = self._build_context(task, context, dst_session, steps)

                # 7. 检查是否需要用户确认（通过卡片）
                if thought_result.get("needs_confirmation"):
                    _LOG.info("[ReActAgent] Step %d requires user confirmation", step_id)
                    # 卡片确认逻辑在外部处理

            except Exception as e:
                _LOG.exception("[ReActAgent] Step %d exception: %s", step_id, str(e))
                steps.append(ReactStep(
                    step_id=step_id,
                    thought=thought if 'thought' in dir() else "",
                    action=action if 'action' in dir() else "unknown",
                    is_error=True,
                    error_message=str(e),
                    duration_ms=int((time.perf_counter() - step_start) * 1000)
                ))
                break

        # 标记会话完成
        total_duration = int((time.perf_counter() - start_time) * 1000)
        self.dst.complete_session(session_id, steps[-1].observation if steps else None)

        result = ReactResult(
            success=len(steps) > 0 and steps[-1].action == "FINAL_ANSWER",
            session_id=session_id,
            steps=steps,
            final_output=steps[-1].observation if steps else None,
            total_steps=len(steps),
            total_duration_ms=total_duration,
            tool_calls=total_tool_calls,
            dst_state=self.dst.get_session_state(session_id)
        )

        _LOG.info("[ReActAgent] Session %s completed: success=%s, steps=%d, duration=%dms",
                  session_id, result.success, result.total_steps, result.total_duration_ms)

        return result

    def _build_context(
        self,
        task: str,
        extra_context: dict,
        dst_session: SkillSession,
        completed_steps: list[ReactStep] = None
    ) -> str:
        """构建发送给LLM的上下文"""
        completed_steps = completed_steps or []

        # 构建技能列表描述
        skills_desc = self._format_skills_list()

        # 构建历史轨迹
        trajectory = ""
        for step in completed_steps[-5:]:  # 最近5步
            trajectory += f"\nStep {step.step_id}:\n"
            trajectory += f"思考: {step.thought[:200]}\n"
            trajectory += f"行动: {step.action}\n"
            if step.observation:
                trajectory += f"观察: {step.observation[:200]}\n"
            if step.is_error:
                trajectory += f"错误: {step.error_message}\n"

        # DST状态摘要
        dst_summary = self._format_dst_summary(dst_session)

        prompt = f"""你是一个复杂系统建模助手。用户的任务是：
{task}

{extra_context.get('system_model', '')}

{dst_summary}

当前技能库：
{skills_desc}

最近执行历史（供参考）：
{trajectory}

请决定下一步行动。

输出格式（严格遵循）：
1. 如果需要调用技能：
Thought: [你的思考过程]
Action: [技能ID]
Action Input: {{"参数名": "参数值"}}

2. 如果任务完成：
Thought: [总结你的工作]
FINAL_ANSWER: [最终答案摘要]

3. 如果需要更多信息或用户确认：
Thought: [说明需要什么]
Action: ask_user
Action Input: {{"question": "你的问题", "options": ["选项1", "选项2"]}}
"""
        return prompt

    def _format_skills_list(self) -> str:
        """格式化技能列表"""
        lines = []
        for skill_id, skill in self.skills.items():
            lines.append(f"- {skill_id}: {skill.metadata.description}")
        return "\n".join(lines) if lines else "无可用技能"

    def _format_dst_summary(self, session: SkillSession) -> str:
        """格式化DST状态摘要"""
        if not session:
            return "DST状态: 新会话"

        parts = []
        if session.user_query:
            parts.append(f"用户意图: {session.user_query}")
        if session.intent:
            parts.append(f"任务类型: {session.intent}")
        if session.actions:
            parts.append(f"已完成操作: {len(session.actions)}步")
            # 列出已识别的变量/关系
            for action in session.actions:
                if action.metadata:
                    if "variables" in action.metadata:
                        parts.append(f"已识别变量: {len(action.metadata['variables'])}个")
                    if "relations" in action.metadata:
                        parts.append(f"已识别关系: {len(action.metadata['relations'])}个")

        return "当前状态:\n" + "\n".join(parts) if parts else "DST状态: 活跃"

    def _llm_think(self, context: str, history: list) -> dict:
        """
        LLM思考决定下一步行动

        Args:
            context: 当前上下文
            history: 执行历史

        Returns:
            dict: 包含 thought, action, action_input, needs_confirmation
        """
        _LOG.debug("[ReActAgent] Calling LLM for decision...")

        messages = [{"role": "user", "content": context}]

        response = self.llm.chat(messages)

        return self._parse_llm_response(response)

    def _parse_llm_response(self, response: Any) -> dict:
        """解析LLM响应，提取行动指令"""
        content = ""
        if hasattr(response, "content"):
            content = response.content
        elif isinstance(response, dict):
            content = response.get("content", "")
        else:
            content = str(response)

        result = {"thought": "", "action": "", "action_input": {}, "needs_confirmation": False}

        lines = content.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("Thought:"):
                result["thought"] = line.replace("Thought:", "").strip()
            elif line.startswith("Action:"):
                result["action"] = line.replace("Action:", "").strip()
            elif line.startswith("Action Input:"):
                # 简单解析JSON
                json_str = line.replace("Action Input:", "").strip()
                try:
                    import json
                    result["action_input"] = json.loads(json_str)
                except:
                    result["action_input"] = {"raw": json_str}
            elif line.startswith("FINAL_ANSWER:"):
                result["action"] = "FINAL_ANSWER"
                result["final_answer"] = line.replace("FINAL_ANSWER:", "").strip()
            elif line.startswith("ask_user") or "确认" in line or "confirm" in line.lower():
                result["needs_confirmation"] = True

        _LOG.debug("[ReActAgent] Parsed response: action=%s, needs_confirm=%s",
                   result["action"], result["needs_confirmation"])

        return result

    def _execute_skill(self, skill_id: str, params: dict) -> tuple[str, bool, Optional[str]]:
        """
        执行技能

        Args:
            skill_id: 技能ID
            params: 技能参数

        Returns:
            (observation, is_error, error_message)
        """
        _LOG.info("[ReActAgent] Executing skill: %s with params: %s", skill_id, params)

        # 查找技能
        skill = self.skills.get(skill_id)
        if not skill:
            return f"技能 '{skill_id}' 不存在", True, f"Unknown skill: {skill_id}"

        # 检查是否需要确认
        if skill.metadata.requires_confirmation:
            _LOG.info("[ReActAgent] Skill %s requires confirmation", skill_id)
            return f"技能 '{skill_id}' 需要用户确认后才能执行", False, None

        try:
            # 验证输入
            valid, errors = skill.validate_input(**params)
            if not valid:
                return f"参数验证失败: {', '.join(errors)}", True, "; ".join(errors)

            # 执行技能
            result = skill.execute(**params)

            # 处理结果
            if isinstance(result, dict):
                if result.get("error"):
                    return str(result["error"]), True, result["error"]
                obs = result.get("observation", "") or result.get("result", "") or str(result)
            else:
                obs = str(result)

            _LOG.info("[ReActAgent] Skill %s executed successfully, result_len=%d",
                      skill_id, len(obs))

            return obs, False, None

        except Exception as e:
            _LOG.exception("[ReActAgent] Skill %s execution failed", skill_id)
            return f"执行失败: {str(e)}", True, str(e)

    def get_skill(self, skill_id: str) -> Optional[AtomicSkill]:
        """获取技能"""
        return self.skills.get(skill_id)

    def register_skill(self, skill_id: str, skill: AtomicSkill) -> None:
        """注册技能"""
        self.skills[skill_id] = skill
        _LOG.info("[ReActAgent] Registered skill: %s", skill_id)
