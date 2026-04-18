"""建模流式半打断 / 强打断：hub 句柄、ReAct/Plan 图与 stop_reason。"""

import json
import threading
from unittest.mock import MagicMock

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage

from uap.config import ContextCompressionConfig
from uap.application.project_service import _modeling_stop_reason
from uap.infrastructure.modeling_stream_hub import (
    USER_HARD_STOP,
    USER_SOFT_STOP,
    ModelingStreamHub,
    get_interrupt_pair_from_context,
)
from uap.react.dst_manager import DstManager
from uap.react.react_agent import ReactAgent
from uap.skill.atomic_skills import AtomicSkill, SkillCategory, SkillMetadata
from uap.plan.plan_agent import PlanAgent, StepStatus


def test_modeling_stop_reason_mapping() -> None:
    assert _modeling_stop_reason(USER_SOFT_STOP) == "soft"
    assert _modeling_stop_reason(USER_HARD_STOP) == "hard"
    assert _modeling_stop_reason(None) is None
    assert _modeling_stop_reason("timeout") is None


def test_get_interrupt_pair_from_context() -> None:
    soft, hard = threading.Event(), threading.Event()
    ip = get_interrupt_pair_from_context({"_interrupt": {"soft": soft, "hard": hard}})
    assert ip is not None
    assert ip[0] is soft and ip[1] is hard
    assert get_interrupt_pair_from_context({}) is None
    assert get_interrupt_pair_from_context(None) is None


def test_modeling_stream_hub_interrupt_signals() -> None:
    hub = ModelingStreamHub()
    sid = "s-test-1"
    hub.create(sid)
    h = hub.get_interrupt_handles(sid)
    assert h is not None
    assert hub.signal_soft_stop(sid) is True
    assert h["soft"].is_set()
    assert hub.signal_hard_stop(sid) is True
    assert h["hard"].is_set()


def test_react_hard_stop_before_llm() -> None:
    m = MagicMock(spec=BaseChatModel)
    m.bind_tools = lambda *a, **k: m
    m.invoke = MagicMock(side_effect=AssertionError("should not invoke"))
    dst = DstManager()
    agent = ReactAgent(
        chat_model=m,
        skills_registry={},
        dst_manager=dst,
        max_iterations=4,
        max_time_seconds=60.0,
        compression_config=ContextCompressionConfig(enabled=False),
    )
    soft, hard = threading.Event(), threading.Event()
    hard.set()
    r = agent.run("t", {"_interrupt": {"soft": soft, "hard": hard}})
    assert r.error_message == USER_HARD_STOP
    assert r.success is False
    assert len(r.steps) == 0
    m.invoke.assert_not_called()


def test_react_soft_stop_after_first_tool_step() -> None:
    meta = SkillMetadata(
        skill_id="echo_tool",
        name="echo",
        description="echo",
        category=SkillCategory.GENERAL,
        input_schema={
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        },
    )
    sk = AtomicSkill(meta)
    sk.set_executor(lambda self, **kw: {"observation": kw.get("msg", "")})

    m = MagicMock(spec=BaseChatModel)
    m.bind_tools = lambda *a, **k: m
    m.invoke = lambda msgs: AIMessage(
        content="",
        tool_calls=[
            {
                "name": "echo_tool",
                "args": {"parameters": {"msg": "x"}},
                "id": "1",
                "type": "tool_call",
            }
        ],
    )

    dst = DstManager()
    agent = ReactAgent(
        chat_model=m,
        skills_registry={"echo_tool": sk},
        dst_manager=dst,
        max_iterations=8,
        max_time_seconds=60.0,
        compression_config=ContextCompressionConfig(enabled=False),
    )
    soft, hard = threading.Event(), threading.Event()
    soft.set()
    r = agent.run("task", {"_interrupt": {"soft": soft, "hard": hard}})
    assert r.error_message == USER_SOFT_STOP
    assert r.success is False
    assert len(r.steps) == 1
    assert r.steps[0].action == "echo_tool"


def test_plan_soft_stop_after_first_executor_step() -> None:
    """Plan：执行一步后若 soft 已置位则不再执行后续 PENDING。"""

    m = MagicMock(spec=BaseChatModel)
    m.bind_tools = lambda *a, **k: m

    plan_payload = [
        {
            "description": "a",
            "tool_name": "echo_tool",
            "tool_params": {"msg": "1"},
            "depends_on": [],
        },
        {
            "description": "b",
            "tool_name": "echo_tool",
            "tool_params": {"msg": "2"},
            "depends_on": [],
        },
    ]

    def _plan_invoke(msgs):
        # ``assistant_text_from_chat_response`` 对 AIMessage 会 ``str()``，破坏 JSON；用 content dict。
        return {"content": json.dumps(plan_payload)}

    m.invoke = _plan_invoke

    meta = SkillMetadata(
        skill_id="echo_tool",
        name="echo",
        description="echo",
        category=SkillCategory.GENERAL,
        input_schema={
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        },
    )
    sk = AtomicSkill(meta)
    sk.set_executor(lambda self, **kw: {"observation": kw.get("msg", "")})

    dst = DstManager()
    agent = PlanAgent(
        chat_model=m,
        skills_registry={"echo_tool": sk},
        dst_manager=dst,
        max_replans=1,
        max_time_seconds=60.0,
        enable_parallel=False,
    )
    soft, hard = threading.Event(), threading.Event()
    soft.set()
    r = agent.run("task", {"_interrupt": {"soft": soft, "hard": hard}})
    assert r.error_message == USER_SOFT_STOP
    assert r.success is False
    completed = [s for s in r.plan if s.status == StepStatus.COMPLETED]
    assert len(completed) == 1
