"""DST 槽位满与模型确认卡策略（与 dst_pipeline / dst_manager 对齐）。"""

from __future__ import annotations

from uap.application.dst_pipeline import (
    DstCompletionPolicy,
    aggregate_should_mark_completed,
    is_dst_slots_full_from_counts,
    is_system_model_slots_full,
)
from uap.project.models import ModelSource, Relation, SystemModel, Variable


def test_slots_full_counts() -> None:
    pol = DstCompletionPolicy(min_variables=1, min_relations=1)
    assert is_dst_slots_full_from_counts(1, 1, pol) is True
    assert is_dst_slots_full_from_counts(0, 1, pol) is False


def test_aggregate_should_mark_completed_without_card() -> None:
    pol = DstCompletionPolicy(require_model_confirm_for_completed=True)
    agg = {
        "project_id": "p1",
        "variables": ["a"],
        "relations": ["r1"],
        "pending_model_confirm": False,
        "model_confirm_acknowledged": False,
    }
    assert aggregate_should_mark_completed(agg, pol) is True


def test_aggregate_requires_ack_when_defer() -> None:
    pol = DstCompletionPolicy(require_model_confirm_for_completed=True)
    agg = {
        "project_id": "p1",
        "variables": ["a"],
        "relations": ["r1"],
        "pending_model_confirm": True,
        "model_confirm_acknowledged": False,
    }
    assert aggregate_should_mark_completed(agg, pol) is False
    agg["model_confirm_acknowledged"] = True
    assert aggregate_should_mark_completed(agg, pol) is True


def test_policy_disables_confirm_requirement() -> None:
    pol = DstCompletionPolicy(require_model_confirm_for_completed=False)
    agg = {
        "variables": ["a"],
        "relations": ["r1"],
        "pending_model_confirm": True,
        "model_confirm_acknowledged": False,
    }
    assert aggregate_should_mark_completed(agg, pol) is True


def test_is_system_model_slots_full() -> None:
    pol = DstCompletionPolicy(min_variables=2, min_relations=1)
    m = SystemModel(
        id="x",
        name="t",
        source=ModelSource.LLM_EXTRACTED,
        variables=[Variable(name="a"), Variable(name="b")],
        relations=[Relation(name="r", effect_var="a")],
    )
    assert is_system_model_slots_full(m, pol) is True
    pol2 = DstCompletionPolicy(min_variables=3, min_relations=1)
    assert is_system_model_slots_full(m, pol2) is False
