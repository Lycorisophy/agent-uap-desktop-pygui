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

**提示词工程**：`_build_context` 使用 ``uap.prompts`` 资产 ``react_decision_user.md`` 拼装
「系统任务 + DST 摘要 + 技能目录 + 轨迹」的单一 user 消息；修改输出格式时需同步
`_parse_llm_response`。

**运行时**：底层编排由 **LangGraph**（``compile_react_graph``）驱动；LangChain
``BaseChatModel`` 负责推理与 ``bind_tools``。

**Harness**：桌面侧通过 `UAPApi.modeling_chat` → `ProjectService.react_modeling`
组装 registry 与本 `ReactAgent`；本文件不依赖 PyWebView，便于单测。
================================================================
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from uap.skill.models import SkillSession
from uap.skill.atomic_skills import AtomicSkill, get_atomic_skills_library
from uap.infrastructure.llm.response_text import assistant_text_from_chat_response
from uap.prompts import PromptId, render
from uap.react.context_helpers import format_system_model_for_prompt
from uap.react.lc_tools import atomic_skills_to_lc_tools

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
        chat_model: BaseChatModel,
        skills_registry: dict[str, AtomicSkill],
        dst_manager,
        max_iterations: int = 10,
        max_time_seconds: float = 120.0,
    ):
        """
        初始化 ReAct Agent。

        Args:
            chat_model: LangChain 聊天模型（``bind_tools`` + ``invoke``）
            skills_registry: **工具注册表**：skill_id → AtomicSkill，对应提示词里的技能列表
            dst_manager: **对话状态 / 上下文工程**侧：建模阶段与槽位填充进度
            max_iterations: 单会话最大推理-行动轮数（防止死循环与费用爆炸）
            max_time_seconds:  wall-clock 超时，与迭代上限二选一先触发者为准
        """
        self.chat_model = chat_model
        self.skills = skills_registry
        self.dst = dst_manager
        self.max_iterations = max_iterations
        self.max_time = max_time_seconds

        self._lc_tools = atomic_skills_to_lc_tools(skills_registry)
        from uap.react.react_graph import compile_react_graph

        self._graph = compile_react_graph(self, self._lc_tools)

        _LOG.info("[ReActAgent] Initialized with %d skills", len(skills_registry))

    def run(self, task: str, context: dict = None) -> ReactResult:
        """
        执行完整 ReAct 会话（**单轮用户输入**下的多步推理-行动）。

        Args:
            task: 用户自然语言任务（进入 DST 与首条上下文）
            context: **Harness 注入槽**：如 ``project_id``、``system_model``（摘要）、
                ``existing_model``（dict，可省略）、RAG 片段等；键名由 ``ProjectService.react_modeling`` 约定。

        Returns:
            含 ``steps``、``dst_state``，供 API 层序列化给前端「进程 / DST」面板。
        """
        session_id = str(uuid.uuid4())
        start_time = time.perf_counter()
        context = context or {}

        _LOG.info("[ReActAgent] Starting session: %s, task: %s", session_id, task[:100])

        dst_session = self.dst.create_session(session_id, task, context)

        final = self._graph.invoke(
            {
                "task": task,
                "extra_context": context,
                "session_id": session_id,
                "dst_session": dst_session,
                "steps": [],
                "llm_rounds": 0,
                "start_time": start_time,
                "finished": False,
                "success": False,
                "error_message": None,
                "total_tool_calls": 0,
                "pending_native": None,
                "pending_text": None,
                "current_step_id": 0,
            }
        )

        steps = list(final.get("steps") or [])
        total_tool_calls = int(final.get("total_tool_calls", 0))
        total_duration = int((time.perf_counter() - start_time) * 1000)

        success = len(steps) > 0 and steps[-1].action == "FINAL_ANSWER"

        self.dst.complete_session(session_id, steps[-1].observation if steps else None)

        result = ReactResult(
            success=success,
            session_id=session_id,
            steps=steps,
            final_output=steps[-1].observation if steps else None,
            error_message=final.get("error_message"),
            total_steps=len(steps),
            total_duration_ms=total_duration,
            tool_calls=total_tool_calls,
            dst_state=self.dst.get_session_state(session_id),
        )

        _LOG.info(
            "[ReActAgent] Session %s completed: success=%s, steps=%d, duration=%dms",
            session_id,
            result.success,
            result.total_steps,
            result.total_duration_ms,
        )

        return result

    def _build_context(
        self,
        task: str,
        extra_context: dict,
        dst_session: SkillSession,
        completed_steps: list[ReactStep] = None,
    ) -> str:
        """
        **上下文工程**：把多源信息压成单条 user 消息（当前 `chat` 接口无独立 system）。

        信息源优先级（概念上）：用户任务 > 注入的 system_model 等 > DST 摘要 >
        技能目录（**工具描述即提示词的一部分**）> 近期轨迹（**工作记忆**）。

        若启用 RAG，上层应把检索片段写入 ``extra_context`` 再调用 ``run``。
        """
        completed_steps = completed_steps or []

        skills_desc = self._format_skills_list()

        trajectory = ""
        for step in completed_steps[-5:]:
            trajectory += f"\nStep {step.step_id}:\n"
            trajectory += f"思考: {step.thought[:200]}\n"
            trajectory += f"行动: {step.action}\n"
            if step.observation:
                trajectory += f"观察: {step.observation[:200]}\n"
            if step.is_error:
                trajectory += f"错误: {step.error_message}\n"

        dst_summary = self._format_dst_summary(dst_session)

        system_model = (extra_context.get("system_model") or "").strip()
        if not system_model:
            em = extra_context.get("existing_model")
            if em:
                system_model = format_system_model_for_prompt(em)

        return render(
            PromptId.REACT_DECISION_USER,
            task=task,
            system_model=system_model,
            dst_summary=dst_summary,
            skills_desc=skills_desc,
            trajectory=trajectory,
        )

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
            for action in session.actions:
                if action.metadata:
                    if "variables" in action.metadata:
                        parts.append(f"已识别变量: {len(action.metadata['variables'])}个")
                    if "relations" in action.metadata:
                        parts.append(f"已识别关系: {len(action.metadata['relations'])}个")

        return "当前状态:\n" + "\n".join(parts) if parts else "DST状态: 活跃"

    def _parse_llm_response(self, response: Any) -> dict:
        """
        **提示词后处理**：把模型自由文本切成 thought/action/input。

        与 **工具系统**的契约：Action 必须为注册表中的 skill_id，或 FINAL_ANSWER /
        ask_user 等保留字。
        """
        if hasattr(response, "content") and not isinstance(response, dict):
            content = response.content
        else:
            content = assistant_text_from_chat_response(response)

        result: dict = {
            "thought": "",
            "action": "",
            "action_input": {},
            "needs_confirmation": False,
        }

        lines = str(content or "").split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("Thought:"):
                result["thought"] = line.replace("Thought:", "").strip()
            elif line.startswith("Action:"):
                result["action"] = line.replace("Action:", "").strip()
            elif line.startswith("Action Input:"):
                json_str = line.replace("Action Input:", "").strip()
                try:
                    import json

                    result["action_input"] = json.loads(json_str)
                except Exception:
                    result["action_input"] = {"raw": json_str}
            elif line.startswith("FINAL_ANSWER:"):
                result["action"] = "FINAL_ANSWER"
                result["final_answer"] = line.replace("FINAL_ANSWER:", "").strip()
            elif line.startswith("ask_user") or "确认" in line or "confirm" in line.lower():
                result["needs_confirmation"] = True

        _LOG.debug(
            "[ReActAgent] Parsed response: action=%s, needs_confirm=%s",
            result["action"],
            result["needs_confirmation"],
        )

        return result

    def _execute_skill(self, skill_id: str, params: dict) -> tuple[str, bool, Optional[str]]:
        """
        **技能与工具执行层**（统一入口）：校验 schema → 调用 ``AtomicSkill.execute``。

        Returns:
            (observation, is_error, error_message) —— observation 将回到下一轮 **上下文工程**。
        """
        _LOG.info("[ReActAgent] Executing skill: %s with params: %s", skill_id, params)

        if skill_id == "ask_user":
            q = params.get("question") or params.get("raw") or str(params)
            return f"（追问用户）{q}", False, None

        skill = self.skills.get(skill_id)
        if not skill:
            return f"技能 '{skill_id}' 不存在", True, f"Unknown skill: {skill_id}"

        if skill.metadata.requires_confirmation:
            _LOG.info("[ReActAgent] Skill %s requires confirmation", skill_id)
            return f"技能 '{skill_id}' 需要用户确认后才能执行", False, None

        try:
            valid, errors = skill.validate_input(**params)
            if not valid:
                return f"参数验证失败: {', '.join(errors)}", True, "; ".join(errors)

            result = skill.execute(**params)

            if isinstance(result, dict):
                if result.get("error"):
                    return str(result["error"]), True, result["error"]
                obs = result.get("observation", "") or result.get("result", "") or str(result)
            else:
                obs = str(result)

            _LOG.info(
                "[ReActAgent] Skill %s executed successfully, result_len=%d",
                skill_id,
                len(obs),
            )

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
        self._lc_tools = atomic_skills_to_lc_tools(self.skills)
        from uap.react.react_graph import compile_react_graph

        self._graph = compile_react_graph(self, self._lc_tools)
        _LOG.info("[ReActAgent] Registered skill: %s", skill_id)
