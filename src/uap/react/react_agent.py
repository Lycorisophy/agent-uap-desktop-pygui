"""
UAP ReAct Agent —— 「八大行动模式」中的 ReAct 实现层
================================================================

与设计文档中「AI 智能体行动模式」的关系（概念映射，便于扩展其它模式）：

1. **ReAct（本模块）**：Thought → Action → Observation 循环；由 LLM 产出结构化
   行动指令，再调用**技能与工具系统**（`AtomicSkill` 注册表）执行并写回观察。
2. **Plan / Workflow**：若未来引入「先规划再执行」，可在 `run()` 外包裹计划器，
   或将多步工具调用编排为 DAG；本模块的 `ReactStep` 序列可作为轨迹日志。
3. **Reflexion / Self-Ask**：可通过在 `_build_context` 中注入「上轮错误摘要」
   实现自我反思；当前以 `completed_steps` 的 observation/error 为载体。
4. **Tool-use / Function Calling**：`_execute_skill` 即统一工具入口；技能元数据
   来自 `atomic_skills`，对应「工具描述 + JSON 参数」的提示词工程。
5. **HITL（人在环）**：`needs_confirmation` 与技能的 `requires_confirmation` 为
   挂点；与 `card_integration`、前端卡片联动在 `project_service.react_modeling`。

**记忆与知识**：本会话内「短期上下文」= `_build_context` 拼接的字符串 +
`SkillSession.actions`；长期记忆应由 `project_store` 消息、`vector`/`history`
等模块负责（见 `config.MemoryConfig`）。

**提示词工程**：`_build_context` 内的 f-string 即「系统任务 + DST 摘要 + 技能目录 +
轨迹」的单一 user 消息模板；修改输出格式时需同步 `_parse_llm_response`。

**上下文工程**：最近 N 步轨迹、DST 摘要、技能列表长度均影响 token；后续可接入
`UapConfig.context_compression` 做预算与摘要。

**Harness**：桌面侧通过 `UAPApi.modeling_chat` → `ProjectService.react_modeling`
组装 registry 与本 `ReactAgent`；本文件不依赖 PyWebView，便于单测。
================================================================
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
    """
    ReAct 单步执行结果（**轨迹 / 记忆写回**的原子单位）

    每一步对应一次「模型决策 → 可选工具执行 → 观察」；序列可用于前端进程面板、
    日志审计与后续 Reflexion 式改进。
    """

    step_id: int  # 从 1 递增，与会话内 DST/ActionNode.step_id 对齐
    thought: str = Field("", description="模型自述推理（提示词要求以 Thought: 开头）")
    action: str = Field("", description="技能 ID、FINAL_ANSWER、或 ask_user 等控制动作")
    action_input: dict = Field(default_factory=dict, description="传给 AtomicSkill.execute 的参数")
    observation: str = Field("", description="工具返回或环境反馈，进入下一轮上下文")
    is_error: bool = False  # 是否为工具/校验失败（影响 DST 与 UI 展示）
    error_message: Optional[str] = None  # 失败时的简短原因，供压缩进上下文
    duration_ms: int = 0  # 单步耗时，用于性能与调度分析


class ReactResult(BaseModel):
    """
    一次 `ReactAgent.run` 的聚合结果（供 **Harness** 层序列化给前端）

    `dst_state` 为 DstManager 的快照，与 `steps` 一起构成可观测的建模会话闭环。
    """

    success: bool  # 是否以 FINAL_ANSWER 正常结束（提前超时/异常则为 False）
    session_id: str  # 与 DST、卡片、项目日志关联的主键
    steps: list[ReactStep] = Field(default_factory=list)
    final_output: Any = None  # 最后一轮产出摘要或观察
    error_message: Optional[str] = None  # 会话级致命错误（若有）
    total_steps: int = 0
    total_duration_ms: int = 0
    tool_calls: int = 0  # 实际工具调用次数（不含纯 FINAL 步）
    dst_state: dict = Field(default_factory=dict, description="DST 状态快照，供前端「建模阶段」展示")


class ReactAgent:
    """
    **ReAct 行动模式**运行时：负责「提示词拼装 → 调 LLM → 解析 → 调技能 → 更新 DST」。

    与 **技能与工具系统**的边界：本类只通过 `skills_registry` 调用 `AtomicSkill`；
    不负责技能的持久化或动态生成（见 `skill/manager.py`、`skill/generator.py`）。

    与 **记忆与知识**的边界：默认只携带本会话 `completed_steps` 与 `dst_session`；
    跨会话检索应在上层注入 `extra_context` 或改用 RAG（`vector/search_service`）。
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
        初始化 ReAct Agent。

        Args:
            llm_client: LLM 客户端（须实现 ``chat(messages) -> ...``，见 OllamaClient）
            skills_registry: **工具注册表**：skill_id → AtomicSkill，对应提示词里的技能列表
            dst_manager: **对话状态 / 上下文工程**侧：建模阶段与槽位填充进度
            max_iterations: 单会话最大推理-行动轮数（防止死循环与费用爆炸）
            max_time_seconds:  wall-clock 超时，与迭代上限二选一先触发者为准
        """
        # --- 运行时依赖（成员说明见类 docstring）---
        self.llm = llm_client  # 推理后端：承担「提示词 → 结构化行动」
        self.skills = skills_registry  # 工具层：ReAct 的 Action 落点
        self.dst = dst_manager  # 状态层：把工具结果折叠为「建模进度」
        self.max_iterations = max_iterations  # 安全预算：步数
        self.max_time = max_time_seconds  # 安全预算：时间

        _LOG.info("[ReActAgent] Initialized with %d skills", len(skills_registry))

    def run(self, task: str, context: dict = None) -> ReactResult:
        """
        执行完整 ReAct 会话（**单轮用户输入**下的多步推理-行动）。

        Args:
            task: 用户自然语言任务（进入 DST 与首条上下文）
            context: **Harness 注入槽**：如 ``project_id``、``existing_model``、
                RAG 片段等；键名由 ``ProjectService.react_modeling`` 约定。

        Returns:
            含 ``steps``、``dst_state``，供 API 层序列化给前端「进程 / DST」面板。
        """
        session_id = str(uuid.uuid4())
        start_time = time.perf_counter()
        context = context or {}

        _LOG.info("[ReActAgent] Starting session: %s, task: %s", session_id, task[:100])

        # DST：建立会话级「槽位+阶段」状态，供 _format_dst_summary 与前端展示
        dst_session = self.dst.create_session(session_id, task, context)

        steps = []
        total_tool_calls = 0
        # 首轮上下文：无历史轨迹，仅任务 + DST + 技能目录
        current_context = self._build_context(task, context, dst_session)

        for iteration in range(self.max_iterations):
            step_start = time.perf_counter()
            # 本轮解析结果（在 except 中也要安全读取）
            thought = ""
            action = ""
            action_input: dict = {}

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
                # 解析或工具链任意环节失败：写入错误步并结束，避免未定义变量
                _LOG.exception("[ReActAgent] Step %d exception: %s", step_id, str(e))
                steps.append(ReactStep(
                    step_id=step_id,
                    thought=thought,
                    action=action or "unknown",
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
        """
        **上下文工程**：把多源信息压成单条 user 消息（当前 `chat` 接口无独立 system）。

        信息源优先级（概念上）：用户任务 > 注入的 system_model 等 > DST 摘要 >
        技能目录（**工具描述即提示词的一部分**）> 近期轨迹（**工作记忆**）。

        若启用 RAG，上层应把检索片段写入 ``extra_context`` 再调用 ``run``。
        """
        completed_steps = completed_steps or []

        # 技能目录：让模型知道可调用的工具 ID 与语义（与提示词末尾格式约束配套）
        skills_desc = self._format_skills_list()

        # 工作记忆：只保留最近 5 步，防止上下文线性膨胀；调参时与 token 预算联动
        trajectory = ""
        for step in completed_steps[-5:]:  # 最近5步
            trajectory += f"\nStep {step.step_id}:\n"
            trajectory += f"思考: {step.thought[:200]}\n"
            trajectory += f"行动: {step.action}\n"
            if step.observation:
                trajectory += f"观察: {step.observation[:200]}\n"
            if step.is_error:
                trajectory += f"错误: {step.error_message}\n"

        # DST：把「槽位填充进度」转成自然语言，引导模型按阶段推进（上下文工程）
        dst_summary = self._format_dst_summary(dst_session)

        # --- 提示词工程（硬编码模板）：修改格式须同步 _parse_llm_response ---
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
        **推理一步**：将上下文发给 LLM，得到下一「行动」。

        Args:
            context: 已由 `_build_context` 拼好的大段 user 文本（当前无多轮 messages）
            history: 预留：多轮对话式 ReAct 时可改为 ``messages`` 列表；现未使用

        Returns:
            解析后的结构化指令，供 ``_execute_skill`` 消费。
        """
        _LOG.debug("[ReActAgent] Calling LLM for decision...")

        # 单条 user：简化 harness；若迁移到 Chat API，建议拆 system/user 并传入 tools
        messages = [{"role": "user", "content": context}]

        response = self.llm.chat(messages)

        return self._parse_llm_response(response)

    def _parse_llm_response(self, response: Any) -> dict:
        """
        **提示词后处理**：把模型自由文本切成 thought/action/input。

        与 **工具系统**的契约：Action 必须为注册表中的 skill_id，或 FINAL_ANSWER /
        ask_user 等保留字。
        """
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
        **技能与工具执行层**（统一入口）：校验 schema → 调用 ``AtomicSkill.execute``。

        Returns:
            (observation, is_error, error_message) —— observation 将回到下一轮 **上下文工程**。
        """
        _LOG.info("[ReActAgent] Executing skill: %s with params: %s", skill_id, params)

        # 从注册表解析可调用对象（工具名与提示词中 Action 一致）
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
