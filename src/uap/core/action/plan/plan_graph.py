"""LangGraph：Plan 模式（规划 → 执行 → 评估 → 必要时重规划）。"""

from __future__ import annotations

import logging
import time
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from uap.core.action.plan.plan_agent import PlanAgent, PlanStep, StepStatus

_LOG = logging.getLogger("uap.core.action.plan.graph")


class PlanState(TypedDict, total=False):
    task: str
    extra_context: dict[str, Any]
    session_id: str
    dst_session: Any
    plan: list[dict[str, Any]]
    replans_done: int
    start_time: float
    finished: bool
    success: bool
    error_message: str | None


def _steps_from_state(state: PlanState) -> list[PlanStep]:
    return [PlanStep.model_validate(x) for x in state.get("plan") or []]


def _dump(steps: list[PlanStep]) -> list[dict[str, Any]]:
    return [s.model_dump() for s in steps]


def _first_executable_pending(steps: list[PlanStep]) -> int:
    """首个依赖已满足的 PENDING 步骤下标；存在 FAILED 时不执行后续 PENDING。"""
    if any(s.status == StepStatus.FAILED for s in steps):
        return -1
    by_id = {s.step_id: s for s in steps}
    for i, s in enumerate(steps):
        if s.status != StepStatus.PENDING:
            continue
        deps = s.depends_on or []
        if not all(by_id.get(d) and by_id[d].status == StepStatus.COMPLETED for d in deps):
            continue
        return i
    return -1


def compile_plan_graph(agent: PlanAgent, lc_tools: list) -> Any:
    _ = lc_tools  # 规划阶段为 JSON 文本；与 ReAct 对齐保留参数便于未来 bind_tools

    def planner(state: PlanState) -> dict[str, Any]:
        if state.get("finished"):
            return {}
        t0 = float(state["start_time"])
        if (time.perf_counter() - t0) > agent.max_time:
            return {
                "finished": True,
                "success": False,
                "error_message": "timeout",
            }

        steps = _steps_from_state(state)
        has_failed = any(s.status == StepStatus.FAILED for s in steps)

        if has_failed:
            rd = int(state.get("replans_done", 0))
            if rd >= agent.max_replans:
                return {
                    "finished": True,
                    "success": False,
                    "error_message": "max_replans_exceeded",
                }
            merged = agent.replan_from_state(state)
            if not merged:
                return {
                    "finished": True,
                    "success": False,
                    "error_message": "replan_empty",
                }
            return {"plan": _dump(merged), "replans_done": rd + 1}

        if steps:
            return {}

        new_steps = agent.generate_plan(
            state["task"],
            state.get("extra_context") or {},
            state["dst_session"],
        )
        if not new_steps:
            return {
                "finished": True,
                "success": False,
                "error_message": "empty_plan",
            }
        return {"plan": _dump(new_steps), "replans_done": 0}

    def executor(state: PlanState) -> dict[str, Any]:
        if state.get("finished"):
            return {}
        t0 = float(state["start_time"])
        if (time.perf_counter() - t0) > agent.max_time:
            return {
                "finished": True,
                "success": False,
                "error_message": "timeout",
            }

        steps = _steps_from_state(state)
        idx = _first_executable_pending(steps)
        if idx < 0:
            return {}

        updated = agent.execute_step(steps[idx], state["session_id"])
        steps[idx] = updated
        return {"plan": _dump(steps)}

    def evaluator(state: PlanState) -> dict[str, Any]:
        if state.get("finished"):
            return {}
        t0 = float(state["start_time"])
        if (time.perf_counter() - t0) > agent.max_time:
            return {
                "finished": True,
                "success": False,
                "error_message": "timeout",
            }

        steps = _steps_from_state(state)
        has_failed = any(s.status == StepStatus.FAILED for s in steps)
        has_pending = any(s.status == StepStatus.PENDING for s in steps)
        repl_done = int(state.get("replans_done", 0))

        if has_failed and repl_done >= agent.max_replans:
            return {
                "finished": True,
                "success": False,
                "error_message": "max_replans_exceeded",
            }
        if has_failed and repl_done < agent.max_replans:
            return {}

        if not has_pending:
            return {"finished": True, "success": True}

        nxt = _first_executable_pending(steps)
        if nxt < 0:
            return {
                "finished": True,
                "success": False,
                "error_message": "plan_deadlock",
            }
        return {}

    def route_after_evaluate(state: PlanState) -> str:
        if state.get("finished"):
            return "end"
        steps = _steps_from_state(state)
        has_failed = any(s.status == StepStatus.FAILED for s in steps)
        repl_done = int(state.get("replans_done", 0))
        if has_failed and repl_done < agent.max_replans:
            return "planner"
        if _first_executable_pending(steps) >= 0:
            return "executor"
        return "end"

    g = StateGraph(PlanState)
    g.add_node("planner", planner)
    g.add_node("executor", executor)
    g.add_node("evaluator", evaluator)
    g.add_edge(START, "planner")
    g.add_edge("planner", "executor")
    g.add_edge("executor", "evaluator")
    g.add_conditional_edges(
        "evaluator",
        route_after_evaluate,
        {"planner": "planner", "executor": "executor", "end": END},
    )
    return g.compile()
