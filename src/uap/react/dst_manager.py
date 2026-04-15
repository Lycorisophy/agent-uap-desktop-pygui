"""
UAP DST对话状态追踪管理器

Dialogue State Tracking - 跟踪智能体在建模过程中的状态变化。
维护变量、关系、约束等建模元素的收集进度。
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
    """建模阶段枚举"""
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
    DST核心状态 - 追踪建模进度

    记录当前会话中已识别的建模元素及其状态。
    """
    session_id: str = Field(default_factory=str)
    project_id: str = ""

    # 建模阶段
    current_stage: ModelingStage = ModelingStage.INITIAL
    stage_history: list[str] = Field(default_factory=list)  # 阶段转换历史

    # 已识别的变量
    variables: dict[str, dict] = Field(default_factory=dict)
    # 已发现的关系
    relations: dict[str, dict] = Field(default_factory=dict)
    # 已定义的约束
    constraints: list[dict] = Field(default_factory=list)

    # 置信度
    variable_confidence: float = 0.0
    relation_confidence: float = 0.0
    overall_confidence: float = 0.0

    # 用户确认状态
    pending_confirmations: list[dict] = Field(default_factory=list)  # 待确认项
    confirmed_items: list[str] = Field(default_factory=list)        # 已确认项

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    last_action_at: Optional[datetime] = None

    class Config:
        use_enum_values = True


class DstManager:
    """
    DST对话状态追踪管理器

    职责：
    1. 为每个会话创建和维护DST状态
    2. 跟踪建模进度（变量→关系→约束）
    3. 评估建模完成度
    4. 触发卡片确认
    """

    def __init__(self):
        """初始化DST管理器"""
        self._sessions: dict[str, SkillSession] = {}  # 技能会话
        self._dst_states: dict[str, DstState] = {}    # DST状态
        self._project_states: dict[str, DstState] = {}  # 项目级DST状态

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
        # 创建SkillSession
        session = SkillSession(
            session_id=session_id,
            project_id=project_id,
            user_query=user_query,
            intent=self._detect_intent(user_query),
            status=SessionStatus.ACTIVE
        )

        # 创建DST状态
        dst_state = DstState(
            session_id=session_id,
            project_id=project_id,
            current_stage=ModelingStage.INTENT_DETECTION
        )

        self._sessions[session_id] = session
        self._dst_states[session_id] = dst_state

        _LOG.info("[DstManager] Created session: %s, intent: %s", session_id, session.intent)

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

        return {
            "current_stage": dst_state.current_stage,
            "variables": list(dst_state.variables.keys()),
            "relations": list(dst_state.relations.keys()),
            "constraints_count": len(dst_state.constraints),
            "progress": self._calculate_progress(dst_state),
            "confidence": dst_state.overall_confidence,
            "pending_confirmations": len(dst_state.pending_confirmations)
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
