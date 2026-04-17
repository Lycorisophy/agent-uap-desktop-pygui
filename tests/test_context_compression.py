"""上下文压缩流水线与模板分段一致性。"""

from __future__ import annotations

import threading
import unittest.mock as mock

from uap.config import ContextCompressionConfig
from uap.prompts import PromptId, render
from uap.react.context_compression import (
    ReactContextParts,
    empty_react_context_parts,
    render_parts,
    run_compression_pipeline,
)
from uap.react.dst_manager import DstManager
from uap.react.react_agent import ReactAgent, ReactStep
from uap.skill.atomic_skills import AtomicSkill, get_atomic_skills_library


class _EchoChat:
    """不调用真实 API：原样返回提示中的「---」之后内容或固定短串。"""

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages, config=None, **kwargs):
        class R:
            content = "摘要后"

        return R()


def _minimal_skills() -> dict[str, AtomicSkill]:
    return {
        sid: AtomicSkill(meta) for sid, meta in get_atomic_skills_library().items()
    }


def test_render_parts_matches_prompt_render():
    task = "hello"
    system_model = "m"
    dst_summary = "d"
    skills_desc = "s"
    trajectory = "t"
    expected = render(
        PromptId.REACT_DECISION_USER,
        task=task,
        system_model=system_model,
        dst_summary=dst_summary,
        skills_desc=skills_desc,
        trajectory=trajectory,
    )
    lit = empty_react_context_parts()
    parts = ReactContextParts(
        literal_pre=lit.literal_pre,
        literal_after_task=lit.literal_after_task,
        literal_after_system_model=lit.literal_after_system_model,
        literal_after_dst=lit.literal_after_dst,
        literal_after_skills=lit.literal_after_skills,
        literal_post=lit.literal_post,
        task=task,
        system_model=system_model,
        dst_summary=dst_summary,
        skills_desc=skills_desc,
        trajectory=trajectory,
    )
    assert render_parts(parts) == expected


def test_pipeline_skipped_when_under_threshold():
    parts = empty_react_context_parts()
    parts.task = "短"
    cfg = ContextCompressionConfig(
        enabled=True,
        context_token_budget=100_000,
        pre_send_threshold=0.99,
        enable_llm_summarization=False,
    )
    out = run_compression_pipeline(
        parts,
        cfg,
        None,
        project_id="p1",
        session_id="sid",
        llm_round=1,
        step_id=1,
        knowledge_ingest=None,
    )
    assert "短" in out
    assert out == render_parts(parts)


def test_truncation_marker_when_budget_tight():
    parts = empty_react_context_parts()
    marker = "[[TEST_TRUNC]]"
    parts.task = "x"
    parts.trajectory = "A" * 50000
    cfg = ContextCompressionConfig(
        enabled=True,
        context_token_budget=4096,
        pre_send_threshold=0.5,
        truncation_marker=marker,
        enable_llm_summarization=False,
        enable_redaction=False,
        enable_async_truncation_kb=False,
        max_trajectory_steps=50,
    )
    out = run_compression_pipeline(
        parts,
        cfg,
        None,
        project_id="proj",
        session_id="sid",
        llm_round=2,
        step_id=3,
        knowledge_ingest=None,
    )
    assert marker in out


def test_no_background_thread_without_project_id():
    parts = empty_react_context_parts()
    parts.trajectory = "B" * 50000
    cfg = ContextCompressionConfig(
        enabled=True,
        context_token_budget=4096,
        pre_send_threshold=0.4,
        enable_llm_summarization=False,
        enable_redaction=False,
        enable_async_truncation_kb=True,
    )
    ingest = mock.Mock()

    with mock.patch.object(threading, "Thread") as Tmock:
        run_compression_pipeline(
            parts,
            cfg,
            None,
            project_id=None,
            session_id="sid",
            llm_round=1,
            step_id=1,
            knowledge_ingest=ingest,
        )
    ingest.assert_not_called()
    Tmock.assert_not_called()


def test_redaction_strips_long_base64():
    parts = empty_react_context_parts()
    parts.trajectory = "x" + ("a" * 100) + "y" + ("z" * 25000)
    cfg = ContextCompressionConfig(
        enabled=True,
        context_token_budget=4096,
        pre_send_threshold=0.35,
        enable_llm_summarization=False,
        enable_redaction=True,
        enable_async_truncation_kb=False,
    )
    out = run_compression_pipeline(
        parts,
        cfg,
        None,
        project_id=None,
        session_id="s",
        llm_round=1,
        step_id=1,
        knowledge_ingest=None,
    )
    assert "[REDACTED_BASE64]" in out or "REDACTED" in out


def test_build_llm_user_content_wires_project_id():
    agent = ReactAgent(
        chat_model=_EchoChat(),
        skills_registry=_minimal_skills(),
        dst_manager=DstManager(),
        compression_config=ContextCompressionConfig(
            enabled=True,
            context_token_budget=4096,
            pre_send_threshold=0.45,
            enable_llm_summarization=True,
            summarization_min_priority=5,
            enable_async_truncation_kb=False,
        ),
    )
    steps = [
        ReactStep(
            step_id=i,
            thought="t",
            action="a",
            observation="O" * 2000,
        )
        for i in range(1, 12)
    ]
    ctx = agent.build_llm_user_content(
        "task",
        {"project_id": "pid"},
        agent.dst.create_session("sid", "task", {}),
        steps,
        session_id="sid",
        llm_round=1,
        step_id=1,
    )
    assert "task" in ctx
