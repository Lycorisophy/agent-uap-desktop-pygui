"""DST 阶段：Pydantic use_enum_values 下 current_stage 为 str 时不应崩溃。"""

import uuid

from uap.react.dst_manager import (
    DstManager,
    ModelingStage,
    _coerce_modeling_stage,
)
from uap.skill.models import ActionNode, ActionType


def test_coerce_modeling_stage_from_str() -> None:
    assert _coerce_modeling_stage("intent") == ModelingStage.INTENT_DETECTION
    assert _coerce_modeling_stage("variables") == ModelingStage.VARIABLE_COLLECTION


def test_add_action_define_variable_when_current_stage_is_str() -> None:
    dst = DstManager()
    sid = str(uuid.uuid4())
    dst.create_session(sid, "建模合肥天气", {"project_id": "p1"})
    ds = dst._dst_states[sid]
    ds.current_stage = "intent"
    act = ActionNode(
        step_id=1,
        type=ActionType.TOOL_CALL,
        tool_name="define_variable",
        metadata={
            "variable": {
                "name": "temperature",
                "description": "空气温度",
                "unit": "°C",
            }
        },
    )
    dst.add_action(sid, act)
    final = _coerce_modeling_stage(dst._dst_states[sid].current_stage)
    # 先进入变量收集；无关系时规则会推进到验证阶段
    assert final in (
        ModelingStage.VARIABLE_COLLECTION,
        ModelingStage.MODEL_VALIDATION,
    )


def test_project_aggregate_merges_two_sessions() -> None:
    dst = DstManager()
    s1 = str(uuid.uuid4())
    s2 = str(uuid.uuid4())
    dst.create_session(s1, "t1", {"project_id": "px"})
    dst.create_session(s2, "t2", {"project_id": "px"})
    a1 = ActionNode(
        step_id=1,
        type=ActionType.TOOL_CALL,
        tool_name="define_variable",
        metadata={"variable": {"name": "a", "description": "d", "unit": "u"}},
    )
    a2 = ActionNode(
        step_id=1,
        type=ActionType.TOOL_CALL,
        tool_name="define_variable",
        metadata={"variable": {"name": "b", "description": "d2", "unit": "u2"}},
    )
    dst.add_action(s1, a1)
    dst.add_action(s2, a2)
    agg = dst.export_project_aggregate_dict("px")
    assert "a" in (agg.get("variables") or [])
    assert "b" in (agg.get("variables") or [])
