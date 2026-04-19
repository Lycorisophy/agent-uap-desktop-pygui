"""
统一 DST 卡片管线 —— 完备性谓词与 pending 键约定（与 ProjectService 协作）
================================================================================
各业务域 schema 不同，但「满槽 →（可选）确认卡 → 确认后 DST 完成」流程一致；
此处仅放可单测的纯函数与小类型，避免在 ProjectService 内复制 if-else。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from uap.settings.models import AgentConfig


def is_modeling_dst_complete(model: Any) -> bool:
    """
    建模槽位「满」的最小判定：至少一条变量且至少一条关系。
    （可后续改为配置化或引入阶段/约束。）
    """
    if model is None:
        return False
    vars_ = getattr(model, "variables", None) or []
    rels = getattr(model, "relations", None) or []
    return len(vars_) > 0 and len(rels) > 0


@dataclass(frozen=True)
class DstCompletionPolicy:
    """DST 流水线标「完成」的槽位与确认策略（与 AgentConfig 对齐）。"""

    min_variables: int = 1
    min_relations: int = 1
    #: 当本轮已挂起模型确认卡（defer）时，是否必须用户点确认后才允许 ``current_stage=completed``
    require_model_confirm_for_completed: bool = True

    @classmethod
    def from_agent(cls, cfg: "AgentConfig | None") -> "DstCompletionPolicy":
        if cfg is None:
            return cls()
        return cls(
            min_variables=max(0, int(getattr(cfg, "dst_min_variables_for_full", 1) or 1)),
            min_relations=max(0, int(getattr(cfg, "dst_min_relations_for_full", 1) or 1)),
            require_model_confirm_for_completed=bool(
                getattr(cfg, "dst_require_model_confirm_for_completed", True)
            ),
        )


def is_dst_slots_full_from_counts(
    n_vars: int, n_rels: int, policy: DstCompletionPolicy
) -> bool:
    return n_vars >= policy.min_variables and n_rels >= policy.min_relations


def is_dst_aggregate_slots_full(aggregate: dict[str, Any], policy: DstCompletionPolicy) -> bool:
    """基于落盘 ``dst_aggregate.json`` 的变量/关系名列表长度判定槽位是否满。"""
    if not isinstance(aggregate, dict):
        return False
    nv = len(aggregate.get("variables") or [])
    nr = len(aggregate.get("relations") or [])
    return is_dst_slots_full_from_counts(nv, nr, policy)


def is_dst_state_slots_full(dst: Any, policy: DstCompletionPolicy) -> bool:
    """基于 ``DstState`` 的 variables/relations 字典大小判定槽位是否满。"""
    vars_ = getattr(dst, "variables", None) or {}
    rels = getattr(dst, "relations", None) or {}
    return is_dst_slots_full_from_counts(len(vars_), len(rels), policy)


def is_system_model_slots_full(model: Any, policy: DstCompletionPolicy) -> bool:
    """与 ``is_modeling_dst_complete`` 一致，但使用 ``DstCompletionPolicy`` 阈值。"""
    if model is None:
        return False
    vars_ = getattr(model, "variables", None) or []
    rels = getattr(model, "relations", None) or []
    return is_dst_slots_full_from_counts(len(vars_), len(rels), policy)


def aggregate_should_mark_completed(
    aggregate: dict[str, Any], policy: DstCompletionPolicy
) -> bool:
    """
    是否可将 ``current_stage`` 标为 ``completed``（槽位满 + 确认策略）。

    - 若 ``require_model_confirm_for_completed`` 为假：槽位满即可。
    - 若为真：本轮曾挂起模型确认卡（``pending_model_confirm``）则必须 ``model_confirm_acknowledged``；
      未挂卡则槽位满即可。
    """
    if not isinstance(aggregate, dict):
        return False
    if not is_dst_aggregate_slots_full(aggregate, policy):
        return False
    if not policy.require_model_confirm_for_completed:
        return True
    if bool(aggregate.get("pending_model_confirm")):
        return bool(aggregate.get("model_confirm_acknowledged"))
    return True


def pending_skill_draft_key(draft_id: str) -> str:
    return f"skill_draft:{draft_id}"


def pending_model_snap_key(snap_id: str) -> str:
    return f"model_snap:{snap_id}"


def parse_pending_key(key: str) -> tuple[str, str] | None:
    """返回 (kind, id) 如 ('skill_draft', uuid) 或 ('model_snap', uuid)。"""
    if key.startswith("skill_draft:"):
        return ("skill_draft", key[len("skill_draft:") :])
    if key.startswith("model_snap:"):
        return ("model_snap", key[len("model_snap:") :])
    return None
