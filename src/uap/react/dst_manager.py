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

import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

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

    def _update_stage(self, state: DstState, tool_name: str, metadata: dict) -> None:
        """根据工具执行情况更新建模阶段"""
        # 阶段转换逻辑
        if tool_name in ["extract_variables", "define_variable", "variable_collector"]:
            if state.current_stage.value < ModelingStage.VARIABLE_COLLECTION.value:
                state.current_stage = ModelingStage.VARIABLE_COLLECTION
                state.stage_history.append(f"{datetime.now().isoformat()}: variables")

        elif tool_name in ["discover_relations", "extract_relations", "relation_finder"]:
            if state.current_stage.value < ModelingStage.RELATION_DISCOVERY.value:
                state.current_stage = ModelingStage.RELATION_DISCOVERY
                state.stage_history.append(f"{datetime.now().isoformat()}: relations")

        elif tool_name in ["define_constraint", "extract_constraints"]:
            if state.current_stage.value < ModelingStage.CONSTRAINT_DEFINITION.value:
                state.current_stage = ModelingStage.CONSTRAINT_DEFINITION
                state.stage_history.append(f"{datetime.now().isoformat()}: constraints")

        elif tool_name in ["validate_model", "model_validator"]:
            state.current_stage = ModelingStage.MODEL_VALIDATION
            state.stage_history.append(f"{datetime.now().isoformat()}: validation")

        elif tool_name in ["configure_prediction", "prediction_setup"]:
            state.current_stage = ModelingStage.PREDICTION_CONFIG

        # 检查完成条件
        if (len(state.variables) >= 1 and
            len(state.relations) >= 0 and
            state.current_stage == ModelingStage.VARIABLE_COLLECTION):
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
        标记会话完成

        Args:
            session_id: 会话ID
            final_output: 最终输出
        """
        if session_id not in self._sessions:
            return

        session = self._sessions[session_id]
        session.status = SessionStatus.COMPLETED
        session.final_output = final_output

        dst_state = self._dst_states.get(session_id)
        if dst_state:
            dst_state.current_stage = ModelingStage.COMPLETED
            self._project_states[dst_state.project_id] = dst_state

        _LOG.info("[DstManager] Session %s completed, final_stage=%s",
                  session_id, dst_state.current_stage if dst_state else "unknown")

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

        # 基础进度
        base_progress = weights.get(state.current_stage, 0.0)

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
