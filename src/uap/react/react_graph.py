"""LangGraph：ReAct 风格循环（与 ``ReactAgent`` 提示词 / DST / 技能执行语义对齐）。"""

from __future__ import annotations

import logging
import time
from functools import reduce
from operator import add
from typing import Any, TypedDict

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langgraph.graph import END, START, StateGraph

from uap.react.react_agent import ReactAgent, ReactStep
from uap.skill.models import ActionNode, ActionType

_LOG = logging.getLogger("uap.react.graph")

# 连续 N 次同一工具且均 is_error 时熔断，避免无效循环拖满步数
_DEFAULT_FAILURE_CIRCUIT = 3


def _repeated_failure_circuit_tripped(
    steps: list[ReactStep],
    consecutive: int = _DEFAULT_FAILURE_CIRCUIT,
) -> bool:
    if len(steps) < consecutive:
        return False
    tail = steps[-consecutive:]
    names = [(getattr(s, "action", "") or "").strip() for s in tail]
    if len(set(names)) != 1:
        return False
    name = names[0]
    if not name or name in ("FINAL_ANSWER", "ask_user", "circuit_breaker"):
        return False
    return all(getattr(s, "is_error", False) for s in tail)


class _ReactState(TypedDict, total=False):
    task: str
    extra_context: dict[str, Any]
    session_id: str
    dst_session: Any
    steps: list[ReactStep]
    llm_rounds: int
    start_time: float
    finished: bool
    success: bool
    error_message: str | None
    total_tool_calls: int
    pending_native: AIMessage | None
    pending_text: dict[str, Any] | None
    current_step_id: int


def _tool_call_to_name_args(tc0: Any) -> tuple[str, dict[str, Any]]:
    """解析 LangChain / OpenAI 风格的单条 tool_call。"""
    import json as _json

    name = ""
    raw_args: Any = None

    if isinstance(tc0, dict):
        name = (tc0.get("name") or "").strip()
        raw_args = tc0.get("args")
        if raw_args is None and isinstance(tc0.get("function"), dict):
            fn = tc0["function"]
            name = (fn.get("name") or name).strip()
            arg_s = fn.get("arguments")
            if isinstance(arg_s, str):
                try:
                    raw_args = _json.loads(arg_s)
                except (_json.JSONDecodeError, TypeError):
                    raw_args = {}
            else:
                raw_args = arg_s
    else:
        name = (getattr(tc0, "name", None) or "").strip()
        raw_args = getattr(tc0, "args", None)

    if not isinstance(raw_args, dict):
        raw_args = {}

    inner = raw_args.get("parameters")
    if isinstance(inner, dict):
        action_input = inner
    else:
        action_input = raw_args
    return name, action_input


def _llm_chunks_to_message(chunks: list[AIMessageChunk]) -> AIMessage:
    """将流式块合并为 AIMessage。

    须保留 ``content`` 为 ``str`` 或块 ``list``（含 ``type:text`` / reasoning），
    供 ``ReactAgent._assistant_message_plain_text`` 展平；**勿**对 list 使用 ``str()``，
    否则 ReAct 解析不到 ``Action:``（表现为 ``empty_action``）。
    """
    if not chunks:
        return AIMessage(content="")
    agg: AIMessageChunk = reduce(add, chunks)
    tc = list(getattr(agg, "tool_calls", None) or [])
    raw = getattr(agg, "content", None)
    if raw is None:
        raw = ""
    if isinstance(raw, (str, list)):
        return AIMessage(content=raw, tool_calls=tc)
    return AIMessage(content=str(raw), tool_calls=tc)


def compile_react_graph(agent: ReactAgent, lc_tools: list) -> Any:
    """编译 LangGraph；``run()`` 通过 ``invoke`` 驱动。"""
    tools = list(lc_tools or [])
    bound = agent.chat_model.bind_tools(tools) if tools else agent.chat_model
    max_ask_user = max(1, int(getattr(agent, "max_ask_user_per_turn", 1) or 1))

    def decide(state: _ReactState) -> dict[str, Any]:
        if state.get("finished"):
            return {}

        start_time = float(state["start_time"])
        if (time.perf_counter() - start_time) > agent.max_time:
            _LOG.warning("[react_graph] Session timed out")
            return {
                "finished": True,
                "success": False,
                "error_message": "timeout",
                "pending_native": None,
                "pending_text": None,
            }

        rounds = int(state.get("llm_rounds", 0)) + 1
        if rounds > agent.max_iterations:
            _LOG.warning("[react_graph] Max iterations reached")
            return {
                "llm_rounds": rounds,
                "finished": True,
                "success": False,
                "error_message": "max_iterations",
                "pending_native": None,
                "pending_text": None,
            }

        steps = list(state.get("steps", []))
        step_id = len(steps) + 1
        if _repeated_failure_circuit_tripped(steps):
            _LOG.warning("[react_graph] Circuit breaker: repeated tool failures (step_id=%d)", step_id)
            trip = ReactStep(
                step_id=step_id,
                thought="",
                action="circuit_breaker",
                observation=(
                    "同一工具已连续多次失败。请勿再重复相同调用；应改用 ask_user "
                    "向用户说明情况并请其提供正确路径或数据位置。"
                )[:500],
                is_error=True,
                error_message="repeated_tool_failures",
                duration_ms=0,
            )
            return {
                "steps": steps + [trip],
                "llm_rounds": int(state.get("llm_rounds", 0)),
                "finished": True,
                "success": False,
                "error_message": "repeated_tool_failures",
                "pending_native": None,
                "pending_text": None,
            }

        task = state["task"]
        extra = state.get("extra_context") or {}
        dst_session = state["dst_session"]

        ctx = agent.build_llm_user_content(
            task,
            extra,
            dst_session,
            steps,
            session_id=state["session_id"],
            llm_round=rounds,
            step_id=step_id,
        )
        _LOG.debug("[react_graph] decide round=%d step_id=%d", rounds, step_id)

        stream_cb = None
        extra_ctx = state.get("extra_context") or {}
        if isinstance(extra_ctx, dict):
            raw_cb = extra_ctx.get("_on_llm_token")
            if callable(raw_cb):
                stream_cb = raw_cb

        try:
            if stream_cb is not None and hasattr(bound, "stream"):
                stream_chunks: list[AIMessageChunk] = []
                for piece in bound.stream([HumanMessage(content=ctx)]):
                    if not isinstance(piece, AIMessageChunk):
                        piece = AIMessageChunk(content=str(piece))
                    stream_chunks.append(piece)
                    delta = ""
                    c = getattr(piece, "content", None)
                    if isinstance(c, str):
                        delta = c
                    elif isinstance(c, list):
                        for block in c:
                            if isinstance(block, dict) and block.get("type") == "text":
                                delta += str(block.get("text") or "")
                    if delta:
                        try:
                            stream_cb(delta)
                        except Exception:
                            _LOG.exception("[react_graph] stream callback failed")
                resp = _llm_chunks_to_message(stream_chunks)
            else:
                resp = bound.invoke([HumanMessage(content=ctx)])
        except Exception as e:
            _LOG.exception("[react_graph] LLM invoke failed")
            err_step = ReactStep(
                step_id=step_id,
                thought="",
                action="unknown",
                is_error=True,
                error_message=str(e),
                duration_ms=0,
            )
            return {
                "steps": steps + [err_step],
                "llm_rounds": rounds,
                "finished": True,
                "success": False,
                "error_message": str(e),
                "pending_native": None,
                "pending_text": None,
            }

        if not isinstance(resp, AIMessage):
            resp = AIMessage(content=str(resp))

        tool_calls = getattr(resp, "tool_calls", None) or []
        if tool_calls:
            return {
                "llm_rounds": rounds,
                "pending_native": resp,
                "pending_text": None,
                "current_step_id": step_id,
            }

        parsed = agent._parse_llm_response(resp)
        thought = parsed.get("thought", "") or ""
        action = (parsed.get("action") or "").strip()
        action_input = parsed.get("action_input") or {}

        # 空 action 不得视为成功结束（否则未产出有效决策也会标记 success）
        if action == "FINAL_ANSWER" or parsed.get("final_answer") is not None:
            fin = ReactStep(
                step_id=step_id,
                thought=thought,
                action="FINAL_ANSWER",
                observation="任务完成",
                duration_ms=0,
            )
            return {
                "steps": steps + [fin],
                "llm_rounds": rounds,
                "finished": True,
                "success": True,
                "pending_native": None,
                "pending_text": None,
            }

        if not action:
            err_step = ReactStep(
                step_id=step_id,
                thought=thought,
                action="",
                is_error=True,
                error_message="empty_action",
                duration_ms=0,
            )
            return {
                "steps": steps + [err_step],
                "llm_rounds": rounds,
                "finished": True,
                "success": False,
                "error_message": "empty_action",
                "pending_native": None,
                "pending_text": None,
            }

        if parsed.get("needs_confirmation"):
            _LOG.info("[react_graph] needs_confirmation (text path) step=%d", step_id)

        return {
            "llm_rounds": rounds,
            "pending_native": None,
            "pending_text": parsed,
            "current_step_id": step_id,
        }

    def route_after_decide(state: _ReactState) -> Any:
        if state.get("finished"):
            return END
        if state.get("pending_native") is not None or state.get("pending_text") is not None:
            return "act"
        return END

    def act(state: _ReactState) -> dict[str, Any]:
        step_start = time.perf_counter()
        steps = list(state.get("steps", []))
        step_id = int(state.get("current_step_id", len(steps) + 1))
        session_id = state["session_id"]

        pending_native = state.get("pending_native")
        pending_text = state.get("pending_text")

        thought = ""
        action = ""
        action_input: dict[str, Any] = {}
        obs = ""
        is_error = False
        err_msg: str | None = None

        if pending_native is not None and isinstance(pending_native, AIMessage):
            thought = (agent._assistant_message_plain_text(pending_native) or "").strip()[
                :5000
            ]
            if not thought:
                ak = getattr(pending_native, "additional_kwargs", None) or {}
                if isinstance(ak, dict):
                    for key in ("reasoning_content", "reasoning", "thinking"):
                        v = ak.get(key)
                        if v:
                            thought = str(v).strip()[:5000]
                            break
                if not thought:
                    rm = getattr(pending_native, "response_metadata", None) or {}
                    if isinstance(rm, dict):
                        for key in ("reasoning_content", "reasoning"):
                            v = rm.get(key)
                            if v:
                                thought = str(v).strip()[:5000]
                                break
            tc_list = pending_native.tool_calls or []
            if not tc_list:
                return {
                    "pending_native": None,
                    "pending_text": None,
                    "finished": True,
                    "success": False,
                    "error_message": "no_tool_calls",
                }
            action, action_input = _tool_call_to_name_args(tc_list[0])

        elif pending_text is not None:
            thought = (pending_text.get("thought") or "")[:5000]
            action = (pending_text.get("action") or "").strip()
            action_input = pending_text.get("action_input") or {}
            if pending_text.get("needs_confirmation"):
                _LOG.info("[react_graph] needs_confirmation step=%d", step_id)
        else:
            return {"pending_native": None, "pending_text": None}

        if action == "FINAL_ANSWER" or not action:
            fin = ReactStep(
                step_id=step_id,
                thought=thought,
                action="FINAL_ANSWER",
                observation="任务完成",
                duration_ms=int((time.perf_counter() - step_start) * 1000),
            )
            return {
                "steps": steps + [fin],
                "finished": True,
                "success": True,
                "pending_native": None,
                "pending_text": None,
            }

        obs, is_error, err_msg = agent._execute_skill(action, action_input)
        duration_ms = int((time.perf_counter() - step_start) * 1000)

        step = ReactStep(
            step_id=step_id,
            thought=thought,
            action=action,
            action_input=action_input,
            observation=obs[:500] if obs else "",
            is_error=is_error,
            error_message=err_msg,
            duration_ms=duration_ms,
        )
        new_steps = steps + [step]

        agent.dst.add_action(
            session_id,
            ActionNode(
                step_id=step_id,
                type=ActionType.TOOL_CALL if not is_error else ActionType.OBSERVATION,
                tool_name=action,
                input_params=action_input,
                output_summary=obs[:200] if obs else "",
                is_error=is_error,
            ),
        )

        extra_tc = 1 if not is_error else 0
        return {
            "steps": new_steps,
            "total_tool_calls": int(state.get("total_tool_calls", 0)) + extra_tc,
            "pending_native": None,
            "pending_text": None,
        }

    def route_after_act(state: _ReactState) -> Any:
        if state.get("finished"):
            return END
        steps = list(state.get("steps") or [])
        if not steps:
            return "decide"
        last = steps[-1]
        if last.action == "ask_user" and not last.is_error:
            n_ok = sum(
                1
                for s in steps
                if getattr(s, "action", "") == "ask_user" and not getattr(s, "is_error", False)
            )
            if n_ok >= max_ask_user:
                _LOG.info(
                    "[react_graph] Stop after ask_user (ok_ask_user=%d, max=%d)",
                    n_ok,
                    max_ask_user,
                )
                return END
        return "decide"

    g = StateGraph(_ReactState)
    g.add_node("decide", decide)
    g.add_node("act", act)
    g.add_edge(START, "decide")
    g.add_conditional_edges("decide", route_after_decide, {END: END, "act": "act"})
    g.add_conditional_edges("act", route_after_act, {END: END, "decide": "decide"})
    return g.compile()
