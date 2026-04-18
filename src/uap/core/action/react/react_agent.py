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
`SkillSession.actions`；跨会话/文档事实可由 Harness 注册的 ``search_knowledge``（Milvus 项目知识库）等工具按需检索；另见 `project_store` 消息与 `config.MemoryConfig`。

**提示词工程**：``build_context_parts`` / ``render_parts`` 与 ``react_decision_user.md`` 对齐；
LangGraph 路径经 ``build_llm_user_content`` 可在发送前按 ``ContextCompressionConfig`` 压缩。
修改输出格式时需同步 ``_parse_llm_response``。

**运行时**：底层编排由 **LangGraph**（``compile_react_graph``）驱动；LangChain
``BaseChatModel`` 负责推理与 ``bind_tools``。

**Harness**：桌面侧通过 `UAPApi.modeling_chat` → `ProjectService.react_modeling`
组装 registry 与本 `ReactAgent`；本文件不依赖 PyWebView，便于单测。
================================================================
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from uap.config import ContextCompressionConfig
from uap.skill.models import SkillSession
from uap.skill.atomic_skills import AtomicSkill, get_atomic_skills_library
from uap.adapters.llm.response_text import assistant_text_from_chat_response
from uap.core.action.react.context_compression import (
    ReactContextParts,
    empty_react_context_parts,
    render_parts,
    run_compression_pipeline,
)
from uap.core.action.react.context_helpers import format_system_model_for_prompt
from uap.infrastructure.modeling_stream_hub import USER_HARD_STOP, USER_SOFT_STOP
from uap.core.action.react.lc_tools import atomic_skills_to_lc_tools

_LOG = logging.getLogger("uap.core.action.react")


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
    pending_user_input: bool = Field(
        default=False,
        description=(
            "本轮 ReAct 图已结束；末步为 ask_user 时需在用户下一条消息中继续（新 invoke），"
            "非同一次图内暂停"
        ),
    )
    session_id: str  # 与 DST、卡片、项目日志关联的主键
    steps: list[ReactStep] = Field(default_factory=list)
    final_output: Any = None  # 最后一轮产出摘要或观察
    error_message: Optional[str] = None  # 会话级致命错误（若有）
    total_steps: int = 0
    total_duration_ms: int = 0
    tool_calls: int = 0  # 实际工具调用次数（不含纯 FINAL 步）
    dst_state: dict = Field(default_factory=dict, description="DST 状态快照，供前端「建模阶段」展示")


def _extract_balanced_json_object(s: str) -> str | None:
    """从字符串开头起找第一个 ``{`` 并做括号平衡，取出完整 JSON 对象子串。"""
    i = s.find("{")
    if i < 0:
        return None
    depth = 0
    for j in range(i, len(s)):
        c = s[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[i : j + 1]
    return None


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
        max_iterations: int = 8,
        max_time_seconds: float = 120.0,
        max_ask_user_per_turn: int = 1,
        compression_config: Optional[ContextCompressionConfig] = None,
        knowledge_service: Any = None,
    ):
        """
        初始化 ReAct Agent。

        Args:
            chat_model: LangChain 聊天模型（``bind_tools`` + ``invoke``）
            skills_registry: **工具注册表**：skill_id → AtomicSkill，对应提示词里的技能列表
            dst_manager: **对话状态 / 上下文工程**侧：建模阶段与槽位填充进度
            max_iterations: 单会话最大推理-行动轮数（防止死循环与费用爆炸）
            max_time_seconds:  wall-clock 超时，与迭代上限二选一先触发者为准
            max_ask_user_per_turn: 单次 ``run`` 内允许的成功 ``ask_user`` 次数，达到后图结束等待用户下一条消息。
            compression_config: 为 ``None`` 时不压缩（等价于 ``ContextCompressionConfig(enabled=False)``）。
            knowledge_service: 可选 ``ProjectKnowledgeService``，用于截断片段异步入库。
        """
        self.chat_model = chat_model
        self.skills = skills_registry
        self.dst = dst_manager
        self.max_iterations = max_iterations
        self.max_time = max_time_seconds
        self.max_ask_user_per_turn = max(1, int(max_ask_user_per_turn or 1))
        self.compression_config = (
            compression_config
            if compression_config is not None
            else ContextCompressionConfig(enabled=False)
        )
        self.knowledge_service = knowledge_service
        self._harness_context: dict = {}

        self._lc_tools = atomic_skills_to_lc_tools(skills_registry)
        from uap.core.action.react.react_graph import compile_react_graph

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
        self._harness_context = dict(context)

        _LOG.info("[ReActAgent] Starting session: %s, task: %s", session_id, task[:100])

        pid = ((context or {}).get("project_id") or "").strip()
        dst_session = self.dst.create_session(session_id, task, context, project_id=pid)

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
        if final.get("error_message") in (USER_SOFT_STOP, USER_HARD_STOP):
            success = False
        pending_user_input = bool(
            steps
            and steps[-1].action == "ask_user"
            and not steps[-1].is_error
            and not success
        )

        self.dst.complete_session(session_id, steps[-1].observation if steps else None)

        result = ReactResult(
            success=success,
            pending_user_input=pending_user_input,
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
        parts = self.build_context_parts(
            task, extra_context, dst_session, completed_steps
        )
        return render_parts(parts)

    def build_context_parts(
        self,
        task: str,
        extra_context: dict,
        dst_session: SkillSession,
        completed_steps: list[ReactStep] | None = None,
    ) -> ReactContextParts:
        """拼装可压缩的结构化上下文（与 ``react_decision_user.md`` 占位符对齐）。"""
        completed_steps = completed_steps or []
        cfg = self.compression_config
        if not cfg.enabled:
            max_steps, t_cap, o_cap = 5, 200, 200
        else:
            max_steps = int(cfg.max_trajectory_steps)
            t_cap = int(cfg.trajectory_thought_max_chars)
            o_cap = int(cfg.trajectory_observation_max_chars)

        parts = empty_react_context_parts()
        parts.task = (task or "").strip()

        skills_desc = self._format_skills_list()
        trajectory = self._format_trajectory(completed_steps, max_steps, t_cap, o_cap)
        dst_summary = self._format_dst_summary(dst_session)

        system_model = (extra_context.get("system_model") or "").strip()
        if not system_model:
            em = extra_context.get("existing_model")
            if em:
                system_model = format_system_model_for_prompt(em)

        parts.system_model = system_model
        parts.dst_summary = dst_summary
        parts.skills_desc = skills_desc
        parts.trajectory = trajectory
        return parts

    def build_llm_user_content(
        self,
        task: str,
        extra_context: dict,
        dst_session: SkillSession,
        completed_steps: list[ReactStep] | None,
        session_id: str,
        llm_round: int,
        step_id: int,
    ) -> str:
        """供 LangGraph ``decide`` 使用：在预算内渲染，必要时走压缩流水线。"""
        parts = self.build_context_parts(
            task, extra_context, dst_session, completed_steps
        )
        ingest = None
        if self.knowledge_service is not None:
            ingest = self.knowledge_service.ingest_truncation_fragments
        body = run_compression_pipeline(
            parts,
            self.compression_config,
            self.chat_model,
            project_id=(extra_context or {}).get("project_id"),
            session_id=session_id,
            llm_round=llm_round,
            step_id=step_id,
            knowledge_ingest=ingest,
        )
        return (
            body
            + self._react_harness_instructions(llm_round)
            + self._deep_search_cot_harness_suffix(extra_context)
        )

    def _deep_search_cot_harness_suffix(self, extra_context: dict | None) -> str:
        """用户开启「深度搜索 + 思维链」时附在编排说明后。"""
        if not (extra_context and extra_context.get("deep_search_cot_mode")):
            return ""
        return (
            "\n- **本轮用户已开启「深度搜索 + 显式思维链」**：需要外部事实时**积极、可多次**调用 "
            "``web_search``；每条 **Thought** 请分步写出（背景/假设 → 检索或工具依据 → 结论与下一步），"
            "避免一句话带过。\n"
        )

    def _react_harness_instructions(self, llm_round: int) -> str:
        """编排层说明：与 LangGraph 停止条件对齐，附在压缩后的用户提示末尾。"""
        t = float(self.max_time)
        t_str = str(int(t)) if t == int(t) else f"{t:.1f}"
        return (
            "\n\n---\n"
            "## 行动模式与编排约束（系统注入）\n"
            "- 当前为 **ReAct**：你输出 Thought → Action → Action Input；"
            "系统执行技能后把观察写入上文的「最近执行历史」。\n"
            f"- **当前决策轮次**（本轮 LLM 调用序号）为 {int(llm_round)}；"
            f"**最大决策轮数**为 {int(self.max_iterations)}。"
            "超过上限时编排器会结束本会话（可能向用户提示已达步数上限）。\n"
            f"- **墙钟超时**约为 {t_str} 秒；与轮数上限**先触发者**为准。\n"
            f"- 成功执行 **ask_user** 累计达到 {int(self.max_ask_user_per_turn)} 次后，"
            "本轮图运行会结束并等待用户**下一条消息**，请勿假设同轮内会继续自动追问。\n"
            "- **工具失败时**：若**同一技能**在最近观察中已连续失败 **2** 次，"
            "必须停止用相同方式重试，改用 **ask_user** 向用户说明错误原因并请其提供路径、文件或数据；"
            "系统也会在连续失败过多时强制结束本轮。\n"
            "- **file_access 路径**：`path` 为相对项目根的路径（如 `data`、`subdir/file.csv`），"
            "不要重复拼项目文件夹名或项目 ID。\n"
        )

    def _format_trajectory(
        self,
        completed_steps: list[ReactStep],
        max_steps: int,
        thought_cap: int,
        obs_cap: int,
    ) -> str:
        if not completed_steps:
            return ""
        tail = completed_steps[-max_steps:]
        lines: list[str] = []
        for step in tail:
            lines.append(f"\nStep {step.step_id}:\n")
            lines.append(f"思考: {step.thought[:thought_cap]}\n")
            lines.append(f"行动: {step.action}\n")
            if step.observation:
                lines.append(f"观察: {step.observation[:obs_cap]}\n")
            if step.is_error and step.error_message:
                lines.append(f"错误: {step.error_message}\n")
        return "".join(lines)

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
        if getattr(session, "scene", None):
            parts.append(f"场景: {session.scene}")
        if session.actions:
            parts.append(f"已完成操作: {len(session.actions)}步")
            for action in session.actions:
                if action.metadata:
                    if "variables" in action.metadata:
                        parts.append(f"已识别变量: {len(action.metadata['variables'])}个")
                    if "relations" in action.metadata:
                        parts.append(f"已识别关系: {len(action.metadata['relations'])}个")

        return "当前状态:\n" + "\n".join(parts) if parts else "DST状态: 活跃"

    def _assistant_message_plain_text(self, response: Any) -> str:
        """从 LangChain 消息或裸 dict/str 中取出可解析的 assistant 文本（含多行 Thought）。"""
        if hasattr(response, "content") and not isinstance(response, dict):
            c = getattr(response, "content", None)
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                parts: list[str] = []
                for block in c:
                    if isinstance(block, str):
                        parts.append(block)
                    elif isinstance(block, dict):
                        t = block.get("type")
                        if t == "text":
                            parts.append(str(block.get("text") or ""))
                        elif t in ("reasoning", "reasoning_content"):
                            parts.append(
                                str(block.get("text") or block.get("reasoning") or "")
                            )
                return "\n".join(parts)
            return str(c or "")
        return assistant_text_from_chat_response(response)

    @staticmethod
    def _is_react_control_line(stripped: str) -> bool:
        """与 ``_format_trajectory`` 中英文标签对齐，便于多行 Thought 在「行动：」等处截断。"""
        return bool(
            stripped
            and (
                stripped.startswith("Thought:")
                or stripped.startswith("Thought：")
                or stripped.startswith("思考:")
                or stripped.startswith("思考：")
                or stripped.startswith("Action:")
                or stripped.startswith("Action：")
                or stripped.startswith("行动:")
                or stripped.startswith("行动：")
                or stripped.startswith("Action Input:")
                or stripped.startswith("Action Input：")
                or stripped.startswith("行动输入:")
                or stripped.startswith("行动输入：")
                or stripped.startswith("FINAL_ANSWER:")
                or stripped.startswith("FINAL_ANSWER：")
                or stripped.startswith("最终答案:")
                or stripped.startswith("最终答案：")
            )
        )

    def _react_apply_parse_fallback(self, plain: str, result: dict) -> None:
        """当行解析未得到 Action 时，兼容 Markdown 围栏、加粗 ``**Action**`` 等变体。"""
        if not plain or not plain.strip():
            return
        if (result.get("action") or "").strip() == "FINAL_ANSWER":
            return

        t = plain.strip()
        if t.startswith("```"):
            t = re.sub(r"^```[a-zA-Z0-9_-]*\s*\n?", "", t, count=1)
            t = re.sub(r"\n?```\s*$", "", t, flags=re.DOTALL).strip()

        fa = re.search(
            r"(?im)(?:^|\n)\s*\*{0,3}\s*(?:FINAL_ANSWER|最终答案)\s*\*{0,3}\s*[:：]\s*(.+?)\s*$",
            t,
        )
        if fa:
            result["action"] = "FINAL_ANSWER"
            result["final_answer"] = fa.group(1).strip()
            return

        if not (result.get("action") or "").strip():
            ac = re.search(
                r"(?im)(?:^|\n)\s*\*{0,3}\s*(?:Action|行动)\s*\*{0,3}\s*[:：]\s*(\S+)",
                t,
            )
            if ac:
                result["action"] = ac.group(1).strip().strip("*").strip()

        # 行内「好的。Action: xxx」等非行首格式（MiniMax 等常见）
        if not (result.get("action") or "").strip():
            loose = list(
                re.finditer(
                    r"(?:Action|行动)\s*[:：]\s*([A-Za-z0-9_]+)",
                    t,
                    flags=re.IGNORECASE | re.DOTALL,
                )
            )
            if loose:
                result["action"] = loose[-1].group(1).strip()

        if not (result.get("action") or "").strip():
            return

        # 行解析已带出非空 action_input 时不再覆盖
        if result.get("action_input"):
            return

        marks = list(
            re.finditer(r"(?im)(?:Action\s*Input|行动输入)\s*[:：]\s*", t),
        )
        if not marks:
            return
        ai_mark = marks[-1]
        tail = t[ai_mark.end() :].lstrip()
        blob = _extract_balanced_json_object(tail)
        if blob:
            try:
                result["action_input"] = json.loads(blob)
            except (json.JSONDecodeError, TypeError):
                result["action_input"] = {"raw": blob}
        else:
            line0 = tail.split("\n", 1)[0].strip()
            if line0:
                try:
                    result["action_input"] = json.loads(line0)
                except (json.JSONDecodeError, TypeError):
                    result["action_input"] = {"raw": line0}

    def _parse_llm_response(self, response: Any) -> dict:
        """
        **提示词后处理**：把模型自由文本切成 thought/action/input。

        与 **工具系统**的契约：Action 必须为注册表中的 skill_id，或 FINAL_ANSWER /
        ask_user 等保留字。
        """
        text = self._assistant_message_plain_text(response)
        result: dict = {
            "thought": "",
            "action": "",
            "action_input": {},
            "needs_confirmation": False,
        }

        lines = str(text or "").split("\n")
        idx_after_thought = 0
        for i, line in enumerate(lines):
            st = line.strip()
            thought_pairs = (
                ("Thought:", "Thought："),
                ("思考:", "思考："),
            )
            matched_thought = None
            for asc, anc in thought_pairs:
                if st.startswith(asc):
                    matched_thought = asc
                    break
                if st.startswith(anc):
                    matched_thought = anc
                    break
            if matched_thought:
                sep = matched_thought
                first = st[len(sep) :].lstrip()
                parts: list[str] = [first] if first else []
                j = i + 1
                while j < len(lines):
                    st2 = lines[j].strip()
                    if self._is_react_control_line(st2) and not (
                        st2.startswith("Thought:")
                        or st2.startswith("Thought：")
                        or st2.startswith("思考:")
                        or st2.startswith("思考：")
                    ):
                        break
                    parts.append(lines[j])
                    j += 1
                result["thought"] = "\n".join(parts).strip()
                idx_after_thought = j
                break

        for line in lines[idx_after_thought:]:
            line = line.strip()
            if line.startswith("Action:") or line.startswith("Action："):
                sep = "Action:" if line.startswith("Action:") else "Action："
                result["action"] = line[len(sep) :].strip()
            elif line.startswith("行动:") or line.startswith("行动："):
                sep = "行动:" if line.startswith("行动:") else "行动："
                result["action"] = line[len(sep) :].strip()
            elif line.startswith("Action Input:") or line.startswith("Action Input："):
                sep = (
                    "Action Input:"
                    if line.startswith("Action Input:")
                    else "Action Input："
                )
                json_str = line[len(sep) :].strip()
                try:
                    result["action_input"] = json.loads(json_str)
                except Exception:
                    result["action_input"] = {"raw": json_str}
            elif line.startswith("行动输入:") or line.startswith("行动输入："):
                sep = (
                    "行动输入:"
                    if line.startswith("行动输入:")
                    else "行动输入："
                )
                json_str = line[len(sep) :].strip()
                try:
                    result["action_input"] = json.loads(json_str)
                except Exception:
                    result["action_input"] = {"raw": json_str}
            elif line.startswith("FINAL_ANSWER:") or line.startswith("FINAL_ANSWER："):
                sep = (
                    "FINAL_ANSWER:"
                    if line.startswith("FINAL_ANSWER:")
                    else "FINAL_ANSWER："
                )
                result["action"] = "FINAL_ANSWER"
                result["final_answer"] = line[len(sep) :].strip()
            elif line.startswith("最终答案:") or line.startswith("最终答案："):
                sep = (
                    "最终答案:"
                    if line.startswith("最终答案:")
                    else "最终答案："
                )
                result["action"] = "FINAL_ANSWER"
                result["final_answer"] = line[len(sep) :].strip()
            elif line.startswith("ask_user") or "确认" in line or "confirm" in line.lower():
                result["needs_confirmation"] = True

        self._react_apply_parse_fallback(str(text or ""), result)

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

        params = dict(params or {})
        hc = getattr(self, "_harness_context", None) or {}
        for k in ("project_workspace",):
            if k in hc and k not in params:
                params[k] = hc[k]

        if skill_id == "ask_user":
            q = params.get("question") or params.get("raw") or str(params)
            return (
                "（已向用户展示上述追问；请用户在下一条消息中直接回复或选择选项，"
                "本轮对话已暂停等待输入。）\n"
                f"（追问用户）{q}"
            ), False, None

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
        from uap.core.action.react.react_graph import compile_react_graph

        self._graph = compile_react_graph(self, self._lc_tools)
        _LOG.info("[ReActAgent] Registered skill: %s", skill_id)
