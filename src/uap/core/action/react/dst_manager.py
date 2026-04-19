"""
UAP DST（Dialogue State Tracking）—— **上下文工程 / 记忆写回** 的结构化视图
================================================================================

DST 与「八大行动模式」的关系：
- 在 **ReAct** 中，DST 不代替模型推理，而是把每步工具结果折叠成「建模阶段 +
  槽位（变量/关系/约束）」，供下一轮 **提示词** 引用，减少模型在长对话中「遗忘进度」。
- 其它模式（如 **Plan-Execute**）可复用同一 ``DstState``，仅在计划器与执行器之间
  更新阶段字段。

与 **记忆与知识系统**：
- ``DstState`` / ``SkillSession`` 偏 **会话内工作记忆**；落盘对话见 ``project_store``
  的 messages；向量检索见 ``vector`` 模块。

与 **技能与工具系统**：
- ``add_action`` 消费 ``ActionNode.metadata`` 中的 variables/relations 等，
  由具体技能在执行成功时写入（约定式接口）。
================================================================================
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from uap.application.dst_pipeline import (
    DstCompletionPolicy,
    aggregate_should_mark_completed,
    is_dst_state_slots_full,
)
from uap.skill.models import ActionNode, ActionType, SkillSession, SessionStatus

_LOG = logging.getLogger("uap.dst")


class ModelingStage(str, Enum):
    """
    建模流水线阶段（**任务型 DST 槽位**），与 UI「DST」页签一致。

    阶段推进可由规则（根据已收集变量数等）或 LLM 在提示词中被引导完成。
    """
    INITIAL = "initial"                 # 初始阶段
    INTENT_DETECTION = "intent"         # 意图识别
    VARIABLE_COLLECTION = "variables"   # 变量收集
    RELATION_DISCOVERY = "relations"    # 关系发现
    CONSTRAINT_DEFINITION = "constraints" # 约束定义
    MODEL_VALIDATION = "validation"      # 模型验证
    PREDICTION_CONFIG = "prediction"    # 预测配置
    COMPLETED = "completed"             # 完成


# 流水线顺序（勿用枚举 .value 做字符串比较，且 Pydantic use_enum_values 下字段常为 str）
_MODELING_STAGE_ORDER: tuple[ModelingStage, ...] = (
    ModelingStage.INITIAL,
    ModelingStage.INTENT_DETECTION,
    ModelingStage.VARIABLE_COLLECTION,
    ModelingStage.RELATION_DISCOVERY,
    ModelingStage.CONSTRAINT_DEFINITION,
    ModelingStage.MODEL_VALIDATION,
    ModelingStage.PREDICTION_CONFIG,
    ModelingStage.COMPLETED,
)


def _coerce_modeling_stage(raw: Any) -> ModelingStage:
    """``DstState`` 在 ``use_enum_values=True`` 时 ``current_stage`` 可能为 str，统一为枚举。"""
    if isinstance(raw, ModelingStage):
        return raw
    if isinstance(raw, str):
        s = raw.strip().lower().removeprefix("modelingstage.")
        try:
            return ModelingStage(s)
        except ValueError:
            _LOG.debug("[DstManager] Unknown modeling stage %r, fallback INITIAL", raw)
            return ModelingStage.INITIAL
    return ModelingStage.INITIAL


def _modeling_stage_rank(stage: ModelingStage) -> int:
    try:
        return _MODELING_STAGE_ORDER.index(stage)
    except ValueError:
        return 0


class DstState(BaseModel):
    """
    **DST 核心状态**：可序列化快照，供 API 返回前端与写入 ``ReactResult.dst_state``。

    与 ``SkillSession`` 分工：后者存 **轨迹**（ActionNode 列表），本类存 **槽位聚合**。
    """
    session_id: str = Field(default_factory=str)  # 与会话 ID 一致
    project_id: str = ""  # 非空时支持项目级统计与多会话合并（预留）

    # --- 阶段机：驱动提示词里的「当前应优先补全哪类槽位」---
    current_stage: ModelingStage = ModelingStage.INITIAL
    stage_history: list[str] = Field(default_factory=list)  # 人类可读阶段变迁，便于审计

    # --- 槽位：从工具 metadata 合并而来，键一般为业务主键名 ---
    variables: dict[str, dict] = Field(default_factory=dict)
    relations: dict[str, dict] = Field(default_factory=dict)
    constraints: list[dict] = Field(default_factory=list)

    # --- 置信度：供后续自动触发 HITL 或排序展示 ---
    variable_confidence: float = 0.0
    relation_confidence: float = 0.0
    overall_confidence: float = 0.0

    # --- HITL：与卡片系统协作的挂点（待确认 / 已确认 ID）---
    pending_confirmations: list[dict] = Field(default_factory=list)  # 待确认项
    confirmed_items: list[str] = Field(default_factory=list)        # 已确认项

    # --- 模型确认卡（MODEL_CONFIRM）与 DST 流水线完成 ---
    pending_model_confirm: bool = False  # 本轮已 defer 模型快照待用户确认
    model_confirm_acknowledged: bool = False  # 用户已在确认卡上确认（或策略不要求卡）

    # --- 元数据 ---
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    last_action_at: Optional[datetime] = None  # 最后工具调用时间，用于超时与 UI

    class Config:
        use_enum_values = True


class DstManager:
    """
    **DST 管理器**：会话生命周期内维护 ``SkillSession`` + ``DstState`` 双表。

    职责摘要：
    1. 创建会话并把用户首句写入 **工作记忆**（user_query / intent）
    2. 每步工具后 ``add_action`` → 解析 metadata → 更新槽位与阶段
    3. ``get_session_state`` 等为 **Harness**（API/前端）提供只读视图
    4. 与 **ReactCardIntegration** 配合实现关键槽位的 HITL（本类存 pending 列表）
    """

    def __init__(self):
        """初始化内存态索引（进程重启后需依赖持久化消息重建，当前为会话内）。"""
        self._sessions: dict[str, SkillSession] = {}  # session_id → 轨迹与计数
        self._dst_states: dict[str, DstState] = {}    # session_id → 槽位快照
        self._project_states: dict[str, DstState] = {}  # project_id → 跨会话聚合（预留）

        _LOG.info("[DstManager] Initialized")

    def create_session(
        self,
        session_id: str,
        user_query: str,
        context: dict = None,
        project_id: str = ""
    ) -> SkillSession:
        """
        创建新的DST会话

        Args:
            session_id: 会话ID
            user_query: 用户原始问题
            context: 额外上下文
            project_id: 项目ID

        Returns:
            SkillSession: 创建的会话对象
        """
        ctx = context or {}
        pid = (ctx.get("project_id") or project_id or "").strip()
        if "classified_intent" in ctx and (ctx.get("classified_intent") or "").strip():
            intent = str(ctx.get("classified_intent")).strip()
        else:
            intent = self._detect_intent(user_query)
        scene = (ctx.get("classified_scene") or "general").strip() or "general"

        # 创建SkillSession
        session = SkillSession(
            session_id=session_id,
            project_id=pid,
            user_query=user_query,
            intent=intent,
            scene=scene,
            status=SessionStatus.ACTIVE
        )

        # 创建DST状态
        dst_state = DstState(
            session_id=session_id,
            project_id=pid,
            current_stage=ModelingStage.INTENT_DETECTION
        )

        self._sessions[session_id] = session
        self._dst_states[session_id] = dst_state

        if pid:
            agg = self._project_states.get(pid)
            if agg is not None:
                dst_state.model_confirm_acknowledged = (
                    dst_state.model_confirm_acknowledged
                    or agg.model_confirm_acknowledged
                )

        _LOG.info(
            "[DstManager] Created session: %s, intent=%s scene=%s",
            session_id,
            session.intent,
            session.scene,
        )

        return session

    def add_action(
        self,
        session_id: str,
        action: ActionNode
    ) -> None:
        """
        添加操作到会话

        Args:
            session_id: 会话ID
            action: 操作节点
        """
        if session_id not in self._sessions:
            _LOG.warning("[DstManager] Session %s not found", session_id)
            return

        session = self._sessions[session_id]
        dst_state = self._dst_states.get(session_id)

        # 添加到会话
        session.add_action(action)

        # 更新DST状态
        if dst_state:
            self._update_dst_state(session_id, action, dst_state)

        session.total_duration_ms += action.duration_ms
        dst_state.last_action_at = datetime.now() if dst_state else None

        _LOG.debug("[DstManager] Added action to session %s: type=%s, tool=%s",
                   session_id, action.type, action.tool_name)

    def _update_dst_state(self, session_id: str, action: ActionNode, state: DstState) -> None:
        """根据操作更新DST状态"""
        tool_name = action.tool_name or ""

        # 从action.metadata中提取建模元素
        metadata = action.metadata or {}

        # 变量收集
        if "variables" in metadata:
            for var in metadata["variables"]:
                var_name = var.get("name", "")
                if var_name:
                    state.variables[var_name] = var
                    _LOG.debug("[DstManager] Variable collected: %s", var_name)

        if "variable" in metadata:
            var = metadata["variable"]
            var_name = var.get("name", "")
            if var_name:
                state.variables[var_name] = var

        # 关系发现
        if "relations" in metadata:
            for rel in metadata["relations"]:
                rel_name = rel.get("name", "")
                if rel_name:
                    state.relations[rel_name] = rel
                    _LOG.debug("[DstManager] Relation discovered: %s", rel_name)

        # 约束定义
        if "constraints" in metadata:
            for constraint in metadata["constraints"]:
                state.constraints.append(constraint)
                _LOG.debug("[DstManager] Constraint defined")

        # 阶段更新
        self._update_stage(state, tool_name, metadata)

        # 更新置信度
        self._update_confidence(state)

        # 检查是否需要确认
        if metadata.get("needs_confirmation"):
            state.pending_confirmations.append({
                "type": metadata.get("confirm_type", "general"),
                "description": metadata.get("confirm_desc", ""),
                "data": metadata.get("confirm_data", {})
            })

        state.updated_at = datetime.now()
        self._merge_dst_into_project_aggregate(state)

    def _merge_dst_into_project_aggregate(self, delta: DstState) -> None:
        """将本会话 DST 槽位合并进 ``project_id`` 级聚合（多会话累积，供提示词与落盘）。"""
        pid = (delta.project_id or "").strip()
        if not pid:
            return
        base = self._project_states.get(pid)
        if base is None:
            base = DstState(
                session_id="_project_aggregate_",
                project_id=pid,
                current_stage=delta.current_stage,
            )
            self._project_states[pid] = base
        base.variables.update(delta.variables)
        base.relations.update(delta.relations)
        existing_sigs = {
            json.dumps(c, sort_keys=True, ensure_ascii=False) for c in base.constraints
        }
        for c in delta.constraints:
            sig = json.dumps(c, sort_keys=True, ensure_ascii=False)
            if sig not in existing_sigs:
                base.constraints.append(c)
                existing_sigs.add(sig)
        cur_b = _coerce_modeling_stage(base.current_stage)
        cur_d = _coerce_modeling_stage(delta.current_stage)
        if _modeling_stage_rank(cur_d) >= _modeling_stage_rank(cur_b):
            base.current_stage = delta.current_stage
        base.variable_confidence = max(base.variable_confidence, delta.variable_confidence)
        base.relation_confidence = max(base.relation_confidence, delta.relation_confidence)
        base.overall_confidence = max(base.overall_confidence, delta.overall_confidence)
        base.pending_model_confirm = bool(delta.pending_model_confirm)
        base.model_confirm_acknowledged = bool(base.model_confirm_acknowledged) or bool(
            delta.model_confirm_acknowledged
        )
        base.updated_at = datetime.now()

    def _update_stage(self, state: DstState, tool_name: str, metadata: dict) -> None:
        """根据工具执行情况更新建模阶段"""
        cur = _coerce_modeling_stage(state.current_stage)
        # 阶段转换逻辑
        if tool_name in ["extract_variables", "define_variable", "variable_collector"]:
            if _modeling_stage_rank(cur) < _modeling_stage_rank(ModelingStage.VARIABLE_COLLECTION):
                state.current_stage = ModelingStage.VARIABLE_COLLECTION
                state.stage_history.append(f"{datetime.now().isoformat()}: variables")

        elif tool_name in ["discover_relations", "extract_relations", "relation_finder"]:
            if _modeling_stage_rank(cur) < _modeling_stage_rank(ModelingStage.RELATION_DISCOVERY):
                state.current_stage = ModelingStage.RELATION_DISCOVERY
                state.stage_history.append(f"{datetime.now().isoformat()}: relations")

        elif tool_name in ["define_constraint", "extract_constraints"]:
            if _modeling_stage_rank(cur) < _modeling_stage_rank(ModelingStage.CONSTRAINT_DEFINITION):
                state.current_stage = ModelingStage.CONSTRAINT_DEFINITION
                state.stage_history.append(f"{datetime.now().isoformat()}: constraints")

        elif tool_name in ["validate_model", "model_validator"]:
            state.current_stage = ModelingStage.MODEL_VALIDATION
            state.stage_history.append(f"{datetime.now().isoformat()}: validation")

        elif tool_name in ["configure_prediction", "prediction_setup"]:
            state.current_stage = ModelingStage.PREDICTION_CONFIG

        # 检查完成条件
        cur2 = _coerce_modeling_stage(state.current_stage)
        if (
            len(state.variables) >= 1
            and len(state.relations) >= 0
            and cur2 == ModelingStage.VARIABLE_COLLECTION
        ):
            # 变量收集足够，可以进入下一阶段
            if state.relation_confidence > 0.5 or not state.relations:
                state.current_stage = ModelingStage.MODEL_VALIDATION

    def _update_confidence(self, state: DstState) -> None:
        """更新建模置信度"""
        # 变量置信度：基于变量数量和定义完整性
        if state.variables:
            complete_vars = sum(
                1 for v in state.variables.values()
                if v.get("description") and v.get("unit")
            )
            state.variable_confidence = complete_vars / len(state.variables)

        # 关系置信度：基于关系定义完整性
        if state.relations:
            complete_rels = sum(
                1 for r in state.relations.values()
                if r.get("description")
            )
            state.relation_confidence = complete_rels / len(state.relations)

        # 整体置信度
        weights = {"variables": 0.5, "relations": 0.3, "constraints": 0.2}
        state.overall_confidence = (
            state.variable_confidence * weights["variables"] +
            state.relation_confidence * weights["relations"] +
            (0.8 if state.constraints else 0.0) * weights["constraints"]
        )

    def complete_session(self, session_id: str, final_output: Any = None) -> None:
        """
        标记 SkillSession 结束。

        DST 是否进入 ``ModelingStage.COMPLETED`` **不**在此处理，而由
        ``apply_pipeline_completion_after_modeling`` 根据槽位满与确认策略提升。
        """
        if session_id not in self._sessions:
            return

        session = self._sessions[session_id]
        session.status = SessionStatus.COMPLETED
        session.final_output = final_output

        dst_state = self._dst_states.get(session_id)
        if dst_state:
            dst_state.updated_at = datetime.now()
            self._merge_dst_into_project_aggregate(dst_state)

        _LOG.info(
            "[DstManager] Session %s skill finished, dst_stage=%s",
            session_id,
            dst_state.current_stage if dst_state else "unknown",
        )

    def seed_project_flags_from_store(
        self, project_id: str, data: dict[str, Any] | None
    ) -> None:
        """从上次落盘的 ``dst_aggregate`` 恢复确认标志，供新会话继承。"""
        pid = (project_id or "").strip()
        if not pid or not isinstance(data, dict):
            return
        st = self._project_states.get(pid)
        if st is None:
            st = DstState(
                session_id="_project_aggregate_",
                project_id=pid,
                current_stage=ModelingStage.INITIAL,
            )
            self._project_states[pid] = st
        st.model_confirm_acknowledged = bool(
            st.model_confirm_acknowledged or data.get("model_confirm_acknowledged")
        )
        st.pending_model_confirm = bool(data.get("pending_model_confirm"))

    def apply_pipeline_completion_after_modeling(
        self,
        session_id: str,
        project_id: str,
        policy: DstCompletionPolicy,
        defer_model_confirm: bool,
    ) -> None:
        """建模一轮结束后：记录是否挂起模型确认卡，并按策略尝试将 DST 标为流水线完成。"""
        dst = self._dst_states.get(session_id)
        if not dst:
            return
        dst.pending_model_confirm = bool(defer_model_confirm)
        dst.updated_at = datetime.now()
        self._try_promote_pipeline_completed(session_id, project_id, policy)

    def _try_promote_pipeline_completed(
        self,
        session_id: str,
        _project_id: str,
        policy: DstCompletionPolicy,
    ) -> None:
        dst = self._dst_states.get(session_id)
        if not dst:
            return
        if not is_dst_state_slots_full(dst, policy):
            return
        if policy.require_model_confirm_for_completed:
            if dst.pending_model_confirm and not dst.model_confirm_acknowledged:
                return
        dst.current_stage = ModelingStage.COMPLETED
        dst.updated_at = datetime.now()
        self._merge_dst_into_project_aggregate(dst)

    def patch_aggregate_dict_for_model_confirm_ack(
        self, aggregate: dict[str, Any], policy: DstCompletionPolicy
    ) -> dict[str, Any]:
        """
        用户已确认模型快照后更新可落盘 aggregate dict，并在内存 project aggregate 存在时同步。
        """
        if not isinstance(aggregate, dict):
            return {}
        out = dict(aggregate)
        out["model_confirm_acknowledged"] = True
        out["pending_model_confirm"] = False
        if aggregate_should_mark_completed(out, policy):
            out["current_stage"] = ModelingStage.COMPLETED.value
            out["progress"] = 1.0
        out["updated_at"] = datetime.now().isoformat()
        pid = str(out.get("project_id") or "").strip()
        if pid:
            st = self._project_states.get(pid)
            if st is not None:
                st.model_confirm_acknowledged = True
                st.pending_model_confirm = False
                if out.get("current_stage") == ModelingStage.COMPLETED.value:
                    st.current_stage = ModelingStage.COMPLETED
                st.updated_at = datetime.now()
        return out

    def export_project_aggregate_dict(self, project_id: str) -> dict[str, Any]:
        """导出 ``project_id`` 下跨会话合并后的 DST 摘要（可 JSON 落盘）。"""
        pid = (project_id or "").strip()
        if not pid:
            return {}
        st = self._project_states.get(pid)
        if not st:
            return {}
        return {
            "project_id": pid,
            "current_stage": _coerce_modeling_stage(st.current_stage).value,
            "variables": list(st.variables.keys()),
            "relations": list(st.relations.keys()),
            "constraints_count": len(st.constraints),
            "progress": self._calculate_progress(st),
            "confidence": st.overall_confidence,
            "pending_model_confirm": bool(getattr(st, "pending_model_confirm", False)),
            "model_confirm_acknowledged": bool(
                getattr(st, "model_confirm_acknowledged", False)
            ),
            "updated_at": st.updated_at.isoformat() if st.updated_at else None,
        }

    def get_session_state(self, session_id: str) -> dict:
        """
        获取会话的DST状态快照

        Args:
            session_id: 会话ID

        Returns:
            dict: DST状态
        """
        dst_state = self._dst_states.get(session_id)
        if not dst_state:
            return {}

        sess = self._sessions.get(session_id)
        intent = getattr(sess, "intent", None) if sess else None
        scene = getattr(sess, "scene", None) if sess else None

        return {
            "current_stage": dst_state.current_stage,
            "variables": list(dst_state.variables.keys()),
            "relations": list(dst_state.relations.keys()),
            "constraints_count": len(dst_state.constraints),
            "progress": self._calculate_progress(dst_state),
            "confidence": dst_state.overall_confidence,
            "pending_confirmations": len(dst_state.pending_confirmations),
            "pending_model_confirm": bool(dst_state.pending_model_confirm),
            "model_confirm_acknowledged": bool(dst_state.model_confirm_acknowledged),
            "intent": intent,
            "scene": scene,
        }

    def _calculate_progress(self, state: DstState) -> float:
        """计算建模进度"""
        weights = {
            ModelingStage.INITIAL: 0.0,
            ModelingStage.INTENT_DETECTION: 0.1,
            ModelingStage.VARIABLE_COLLECTION: 0.4,
            ModelingStage.RELATION_DISCOVERY: 0.6,
            ModelingStage.CONSTRAINT_DEFINITION: 0.75,
            ModelingStage.MODEL_VALIDATION: 0.9,
            ModelingStage.PREDICTION_CONFIG: 0.95,
            ModelingStage.COMPLETED: 1.0
        }

        # 基础进度（current_stage 可能为 str）
        base_progress = weights.get(_coerce_modeling_stage(state.current_stage), 0.0)

        # 根据收集的元素调整
        var_bonus = min(len(state.variables) * 0.05, 0.1)
        rel_bonus = min(len(state.relations) * 0.05, 0.1)

        return min(base_progress + var_bonus + rel_bonus, 1.0)

    def get_pending_confirmations(self, session_id: str) -> list[dict]:
        """获取待确认项"""
        dst_state = self._dst_states.get(session_id)
        return dst_state.pending_confirmations if dst_state else []

    def confirm_item(self, session_id: str, item_id: str) -> bool:
        """确认一个建模元素"""
        dst_state = self._dst_states.get(session_id)
        if not dst_state:
            return False

        dst_state.confirmed_items.append(item_id)
        dst_state.pending_confirmations = [
            c for c in dst_state.pending_confirmations
            if c.get("id") != item_id
        ]
        return True

    def get_model_summary(self, session_id: str) -> dict:
        """
        获取建模摘要

        Args:
            session_id: 会话ID

        Returns:
            dict: 建模摘要
        """
        dst_state = self._dst_states.get(session_id)
        if not dst_state:
            return {}

        return {
            "variables": list(dst_state.variables.values()),
            "relations": list(dst_state.relations.values()),
            "constraints": dst_state.constraints,
            "stage": dst_state.current_stage,
            "progress": self._calculate_progress(dst_state),
            "confidence": dst_state.overall_confidence,
            "confirmed": dst_state.confirmed_items
        }

    def _detect_intent(self, query: str) -> str:
        """
        从用户查询中检测意图

        Args:
            query: 用户查询

        Returns:
            str: 检测到的意图
        """
        query_lower = query.lower()

        if any(kw in query_lower for kw in ["预测", "forecast", "predict", "未来"]):
            return "prediction"
        elif any(kw in query_lower for kw in ["异常", "anomaly", "异常检测"]):
            return "anomaly_detection"
        elif any(kw in query_lower for kw in ["建模", "model", "系统"]):
            return "system_modeling"
        elif any(kw in query_lower for kw in ["分析", "analyze", "分析"]):
            return "analysis"
        else:
            return "general"

    def get_session(self, session_id: str) -> Optional[SkillSession]:
        """获取会话对象"""
        return self._sessions.get(session_id)

    def list_sessions(self, project_id: str = None) -> list[str]:
        """列出所有会话"""
        if project_id:
            return [
                sid for sid, s in self._sessions.items()
                if s.project_id == project_id
            ]
        return list(self._sessions.keys())

    def cleanup_old_sessions(self, max_age_seconds: int = 3600) -> int:
        """
        清理旧会话

        Args:
            max_age_seconds: 最大保留时间

        Returns:
            int: 清理的会话数
        """
        now = datetime.now()
        to_remove = []

        for session_id, session in self._sessions.items():
            if session.status == SessionStatus.COMPLETED:
                age = (now - session.end_time).total_seconds() if session.end_time else 0
                if age > max_age_seconds:
                    to_remove.append(session_id)

        for session_id in to_remove:
            del self._sessions[session_id]
            self._dst_states.pop(session_id, None)

        if to_remove:
            _LOG.info("[DstManager] Cleaned up %d old sessions", len(to_remove))

        return len(to_remove)
