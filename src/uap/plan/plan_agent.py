"""
Plan 行动模式：先规划、再逐步执行，失败时在预算内重规划。
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from enum import Enum
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from uap.infrastructure.llm.response_text import assistant_text_from_chat_response
from uap.prompts import PromptId, render
from uap.react.lc_tools import atomic_skills_to_lc_tools
from uap.skill.atomic_skills import AtomicSkill
from uap.skill.models import ActionNode, ActionType

_LOG = logging.getLogger("uap.plan.agent")


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanStep(BaseModel):
    """计划中的一步（可序列化进 LangGraph 状态）。"""

    step_id: int
    description: str = ""
    tool_name: Optional[str] = None
    tool_params: Optional[dict[str, Any]] = None
    depends_on: list[int] = Field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    observation: Optional[str] = None
    error: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None


class PlanResult(BaseModel):
    """一次 Plan 会话的聚合结果。"""

    success: bool
    session_id: str
    plan: list[PlanStep] = Field(default_factory=list)
    final_output: Any = None
    error_message: Optional[str] = None
    total_steps: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    replan_count: int = 0
    total_duration_ms: int = 0
    dst_state: dict = Field(default_factory=dict)


def _extract_json_array(text: str) -> list[dict[str, Any]]:
    """从模型输出中解析 JSON 数组。"""
    raw = (text or "").strip()
    if not raw:
        return []
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if m:
        raw = m.group(1).strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end <= start:
        return []
    blob = raw[start : end + 1]
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        _LOG.warning("[PlanAgent] JSON parse failed, snippet=%s", blob[:200])
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict):
            out.append(item)
    return out


class PlanAgent:
    """
    Plan 行动模式：生成结构化步骤列表，顺序（或可并行）执行，失败时重规划。
    """

    def __init__(
        self,
        chat_model: BaseChatModel,
        skills_registry: dict[str, AtomicSkill],
        dst_manager: Any,
        max_replans: int = 3,
        max_time_seconds: float = 300.0,
        enable_parallel: bool = False,
    ):
        self.chat_model = chat_model
        self.skills = skills_registry
        self.dst = dst_manager
        self.max_replans = max_replans
        self.max_time = max_time_seconds
        self.enable_parallel = enable_parallel
        self._lc_tools = atomic_skills_to_lc_tools(skills_registry)
        from uap.plan.plan_graph import compile_plan_graph

        self._graph = compile_plan_graph(self, self._lc_tools)

    def run(self, task: str, context: dict | None = None) -> PlanResult:
        session_id = str(uuid.uuid4())
        start = time.perf_counter()
        context = context or {}
        pid = (context.get("project_id") or "").strip()
        dst_session = self.dst.create_session(session_id, task, context, project_id=pid)

        final_state = self._graph.invoke(
            {
                "task": task,
                "extra_context": context,
                "session_id": session_id,
                "dst_session": dst_session,
                "plan": [],
                "replans_done": 0,
                "start_time": start,
                "finished": False,
                "success": False,
                "error_message": None,
            }
        )

        plan_raw = final_state.get("plan") or []
        plan = [PlanStep.model_validate(x) for x in plan_raw]
        completed = sum(1 for s in plan if s.status == StepStatus.COMPLETED)
        failed = sum(1 for s in plan if s.status == StepStatus.FAILED)
        success = bool(final_state.get("success"))
        fo = self._format_final_output(plan)

        self.dst.complete_session(session_id, fo)

        return PlanResult(
            success=success,
            session_id=session_id,
            plan=plan,
            final_output=fo,
            error_message=final_state.get("error_message"),
            total_steps=len(plan),
            completed_steps=completed,
            failed_steps=failed,
            replan_count=int(final_state.get("replans_done", 0)),
            total_duration_ms=int((time.perf_counter() - start) * 1000),
            dst_state=self.dst.get_session_state(session_id),
        )

    def generate_plan(
        self, task: str, extra_context: dict, dst_session: Any
    ) -> list[PlanStep]:
        skills_desc = self._format_skills_list()
        system_model = (extra_context.get("system_model") or "").strip()
        if not system_model:
            em = extra_context.get("existing_model")
            if em:
                from uap.react.context_helpers import format_system_model_for_prompt

                system_model = format_system_model_for_prompt(em)

        prompt = render(
            PromptId.PLAN_GENERATION_USER,
            task=task or "",
            system_model=system_model or "（无）",
            skills_desc=skills_desc,
        )
        resp = self.chat_model.invoke([HumanMessage(content=prompt)])
        text = assistant_text_from_chat_response(resp)
        items = _extract_json_array(str(text))
        steps: list[PlanStep] = []
        for i, item in enumerate(items, start=1):
            deps = item.get("depends_on") or []
            if not isinstance(deps, list):
                deps = []
            deps_i: list[int] = []
            for d in deps:
                try:
                    if isinstance(d, bool):
                        continue
                    if isinstance(d, int):
                        deps_i.append(d)
                    elif isinstance(d, float):
                        deps_i.append(int(d))
                    elif isinstance(d, str) and d.strip().lstrip("-").isdigit():
                        deps_i.append(int(d.strip()))
                except (TypeError, ValueError):
                    continue
            tn = item.get("tool_name")
            if isinstance(tn, str):
                tn = tn.strip() or None
            else:
                tn = None
            tp = item.get("tool_params")
            if tp is not None and not isinstance(tp, dict):
                tp = {}
            steps.append(
                PlanStep(
                    step_id=i,
                    description=str(item.get("description") or "").strip() or f"步骤{i}",
                    tool_name=tn,
                    tool_params=tp if isinstance(tp, dict) else {},
                    depends_on=deps_i,
                )
            )
        _LOG.info("[PlanAgent] Generated plan: %d steps", len(steps))
        return steps

    def replan_from_state(self, state: dict[str, Any]) -> list[PlanStep]:
        """保留已完成步骤，用 LLM 生成新的后续 ``PlanStep`` 列表（新 step_id 顺延）。"""
        raw = state.get("plan") or []
        steps = [PlanStep.model_validate(x) for x in raw]
        completed = [s for s in steps if s.status == StepStatus.COMPLETED]
        next_id = max((s.step_id for s in completed), default=0) + 1

        task = state["task"]
        original = self._format_plan_for_prompt(steps)
        trajectory = self._format_execution_trajectory(steps)

        prompt = render(
            PromptId.PLAN_REPLAN_USER,
            task=task or "",
            original_plan=original,
            trajectory=trajectory,
        )
        resp = self.chat_model.invoke([HumanMessage(content=prompt)])
        text = assistant_text_from_chat_response(resp)
        items = _extract_json_array(str(text))
        new_steps: list[PlanStep] = []
        for item in items:
            tp = item.get("tool_params")
            if tp is not None and not isinstance(tp, dict):
                tp = {}
            tn = item.get("tool_name")
            if isinstance(tn, str):
                tn = tn.strip() or None
            else:
                tn = None
            new_steps.append(
                PlanStep(
                    step_id=next_id,
                    description=str(item.get("description") or "").strip() or f"步骤{next_id}",
                    tool_name=tn,
                    tool_params=tp if isinstance(tp, dict) else {},
                    depends_on=[],
                    status=StepStatus.PENDING,
                )
            )
            next_id += 1
        merged = completed + new_steps
        _LOG.info("[PlanAgent] Replanned: kept %d completed, +%d new", len(completed), len(new_steps))
        return merged

    def execute_step(self, step: PlanStep, session_id: str) -> PlanStep:
        t0 = time.perf_counter()
        step = step.model_copy(deep=True)
        step.status = StepStatus.RUNNING
        step.start_time = t0
        params = dict(step.tool_params or {})

        if step.tool_name:
            obs, is_error, err_msg = self._execute_skill(step.tool_name, params)
            step.observation = obs
            if is_error:
                step.status = StepStatus.FAILED
                step.error = err_msg
            else:
                step.status = StepStatus.COMPLETED
        else:
            step.observation = f"（无工具）{step.description}"
            step.status = StepStatus.COMPLETED

        step.end_time = time.perf_counter()
        dur_ms = int((step.end_time - (step.start_time or step.end_time)) * 1000)

        self.dst.add_action(
            session_id,
            ActionNode(
                step_id=step.step_id,
                type=ActionType.TOOL_CALL if step.tool_name else ActionType.OBSERVATION,
                tool_name=step.tool_name or "plan_step",
                input_params=params,
                output_summary=(step.observation or "")[:200],
                duration_ms=dur_ms,
                is_error=step.status == StepStatus.FAILED,
            ),
        )
        return step

    def _execute_skill(self, skill_id: str, params: dict) -> tuple[str, bool, Optional[str]]:
        _LOG.info("[PlanAgent] Executing skill: %s params=%s", skill_id, params)
        if skill_id == "ask_user":
            q = params.get("question") or params.get("raw") or str(params)
            return f"（追问用户）{q}", False, None
        skill = self.skills.get(skill_id)
        if not skill:
            return f"技能 '{skill_id}' 不存在", True, f"Unknown skill: {skill_id}"
        if skill.metadata.requires_confirmation:
            return f"技能 '{skill_id}' 需要用户确认后才能执行", False, None
        try:
            valid, errors = skill.validate_input(**params)
            if not valid:
                return f"参数验证失败: {', '.join(errors)}", True, "; ".join(errors)
            result = skill.execute(**params)
            if isinstance(result, dict):
                if result.get("error"):
                    return str(result["error"]), True, str(result["error"])
                obs = result.get("observation", "") or result.get("result", "") or str(result)
            else:
                obs = str(result)
            return obs, False, None
        except Exception as e:
            _LOG.exception("[PlanAgent] Skill %s failed", skill_id)
            return f"执行失败: {e}", True, str(e)

    def _format_skills_list(self) -> str:
        lines = []
        for skill_id, skill in self.skills.items():
            lines.append(f"- {skill_id}: {skill.metadata.description}")
        return "\n".join(lines) if lines else "无可用技能"

    def _format_plan_for_prompt(self, steps: list[PlanStep]) -> str:
        lines = []
        for s in steps:
            lines.append(
                f"- id={s.step_id} status={s.status.value} desc={s.description!r} "
                f"tool={s.tool_name!r} err={s.error!r}"
            )
        return "\n".join(lines) if lines else "（空）"

    def _format_execution_trajectory(self, steps: list[PlanStep]) -> str:
        lines = []
        for s in steps:
            if s.status not in (StepStatus.COMPLETED, StepStatus.FAILED):
                continue
            lines.append(f"步骤 {s.step_id}: {s.description}")
            if s.tool_name:
                lines.append(f"  工具: {s.tool_name} 参数: {s.tool_params}")
            if s.observation:
                lines.append(f"  观察: {s.observation[:500]}")
            if s.error:
                lines.append(f"  错误: {s.error}")
        return "\n".join(lines) if lines else "（尚无执行记录）"

    def _format_final_output(self, plan: list[PlanStep]) -> str:
        parts = [s.observation for s in plan if s.observation and s.status == StepStatus.COMPLETED]
        if parts:
            return parts[-1]
        errs = [s.error for s in plan if s.error]
        if errs:
            return errs[-1] or ""
        return ""
