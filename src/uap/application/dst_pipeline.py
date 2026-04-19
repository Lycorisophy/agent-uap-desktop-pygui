"""
统一 DST 卡片管线 —— 完备性谓词与 pending 键约定（与 ProjectService 协作）
================================================================================
各业务域槽位 schema 不同，但「满槽 → 确认卡 → 确认后执行」流程一致；
此处仅放可单测的纯函数与小类型，避免在 ProjectService 内复制 if-else。
"""

from __future__ import annotations

from typing import Any


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
