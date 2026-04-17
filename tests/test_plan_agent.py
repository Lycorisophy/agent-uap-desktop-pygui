"""Plan 模式：提示词渲染与最小 LangGraph 跑通。"""

from __future__ import annotations

from uap.plan.plan_agent import PlanAgent, StepStatus
from uap.prompts import PromptId, render
from uap.react.dst_manager import DstManager


def test_plan_generation_prompt_renders() -> None:
    text = render(
        PromptId.PLAN_GENERATION_USER,
        task="预测销量",
        system_model="（无）",
        skills_desc="- a: test",
    )
    assert "预测销量" in text
    assert "JSON" in text or "json" in text


def test_plan_replan_prompt_renders() -> None:
    text = render(
        PromptId.PLAN_REPLAN_USER,
        task="t",
        original_plan="- id=1",
        trajectory="（无）",
    )
    assert "t" in text


def test_plan_run_single_no_tool_step() -> None:
    payload = (
        '[{"description":"确认目标范围","tool_name":"","tool_params":{},'
        '"depends_on":[]}]'
    )

    class _FakeChat:
        def bind_tools(self, tools, **kwargs):
            return self

        def invoke(self, messages, **kwargs):
            return {"message": {"content": payload}}

    agent = PlanAgent(
        chat_model=_FakeChat(),
        skills_registry={},
        dst_manager=DstManager(),
        max_replans=2,
        max_time_seconds=60.0,
    )
    res = agent.run("hello", {"project_id": "p1"})
    assert res.success
    assert len(res.plan) == 1
    assert res.plan[0].status == StepStatus.COMPLETED
    assert res.plan[0].step_id == 1


def test_extract_json_array_with_fence() -> None:
    from uap.plan.plan_agent import _extract_json_array

    raw = """Here:
```json
[{"description":"x","tool_name":null}]
```
"""
    arr = _extract_json_array(raw)
    assert len(arr) == 1
    assert arr[0]["description"] == "x"
