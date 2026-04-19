"""
ProjectService —— **领域编排层**（介于 Harness ``UAPApi`` 与存储 ``ProjectStore`` 之间）
================================================================================

典型链路：
- **建模**：``modeling_chat`` / ``react_modeling`` / ``plan_modeling`` —— 组装 LLM、
  ReAct 或 Plan 模式、技能注册表、DST、卡片（**RADH** 以 ReAct 为主路径）。
- **记忆**：对话 JSON、系统模型文件经 ``ProjectStore``；可选向量检索在 API/服务扩展。
- **提示词/上下文**：ReAct 主模板在 ``uap.prompts``；本服务负责 **注入业务事实**
  （含 ``system_model`` 文本摘要与 ``existing_model`` dict）。

不宜在本类直接写 PyWebView 或 HTTP 路由逻辑，保持可单测。
================================================================================
"""

from __future__ import annotations

import logging
import sys
import uuid
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any, Optional

from uap.config import LLMConfig, UapConfig
from uap.infrastructure.knowledge import ProjectKnowledgeService
from uap.infrastructure.llm import ModelExtractor
from uap.infrastructure.llm.factory import create_llm_chat_client
from uap.infrastructure.llm.langchain_chat_model import create_langchain_chat_model
from uap.infrastructure.modeling_stream_hub import USER_HARD_STOP, USER_SOFT_STOP
from uap.infrastructure.persistence.project_store import ProjectStore, user_workspace_dir
from uap.project.models import (
    ModelSource,
    PredictionConfig,
    ProjectStatus,
    SystemModel,
    Variable,
    Relation,
)
from uap.application.dst_pipeline import (
    is_modeling_dst_complete,
    pending_model_snap_key,
    pending_skill_draft_key,
)
from uap.application.modeling_intent_classifier import (
    build_modeling_task_with_prior_dialogue,
    run_modeling_intent_scene_if_enabled,
)
from uap.card.models import CardOption, CardPriority, CardResponse, CardType, ConfirmationCard
from uap.react.ask_user_card import build_ask_user_confirmation_card
from uap.react.context_helpers import format_system_model_for_prompt

_LOG = logging.getLogger("uap.project_service")


def _modeling_stop_reason(error_message: str | None) -> str | None:
    if error_message == USER_SOFT_STOP:
        return "soft"
    if error_message == USER_HARD_STOP:
        return "hard"
    return None


class ProjectService:
    """
    项目级用例的 **编排服务**：创建/打开项目、持久化消息、触发 **行动模式** 建模、
    与文档导入、模型抽取等交叉能力。

    依赖注入：``store`` 管文件与 SQLite 侧持久化；``cfg`` 提供 LLM/记忆/上下文开关。
    """

    def __init__(
        self,
        store: ProjectStore,
        cfg: UapConfig,
        extractor: Optional[ModelExtractor] = None
    ) -> None:
        """
        初始化项目服务
        
        Args:
            store: 项目存储实例
            cfg: 应用配置
            extractor: 模型提取器，默认创建Ollama提取器
        """
        self._store = store
        self._cfg = cfg
        self._knowledge = ProjectKnowledgeService(cfg)
        from uap.infrastructure.llm.model_extractor import ModelExtractor

        try:
            llm_client = create_llm_chat_client(cfg.llm)
        except ValueError as e:
            _LOG.warning("LLM 配置不完整，回退默认 Ollama 客户端用于抽取: %s", e)
            llm_client = create_llm_chat_client(LLMConfig())
        self._extractor = extractor or ModelExtractor(llm_client)
        self._pending_skill_drafts: dict[str, dict[str, Any]] = {}
        self._pending_model_snapshots: dict[str, dict[str, Any]] = {}
        self._card_to_pending: dict[str, str] = {}
        self._dst_card_cm_id: int | None = None
        self._api_card_manager: Any = None

    def attach_card_manager(self, card_manager: Any) -> None:
        """由 UAPApi 在构造后调用一次：注册 DST 确认卡回调与过期清理。"""
        if card_manager is None:
            return
        self._api_card_manager = card_manager
        if self._dst_card_cm_id == id(card_manager):
            return
        self._dst_card_cm_id = id(card_manager)
        card_manager.register_callback(
            CardType.SKILL_DRAFT_CONFIRM, self._on_skill_draft_card_response
        )
        card_manager.register_callback(CardType.MODEL_CONFIRM, self._on_model_confirm_card_response)
        card_manager.register_on_pending_card_removed(self._on_pending_card_expired_cleanup)

    def _on_pending_card_expired_cleanup(self, card: ConfirmationCard, reason: str) -> None:
        if reason != "expired":
            return
        self._card_to_pending.pop(card.card_id, None)
        pk = (card.context or {}).get("pending_key")
        if isinstance(pk, str):
            self._purge_pending_payload_by_key(pk)

    def _purge_pending_payload_by_key(self, pending_key: str) -> None:
        from uap.application.dst_pipeline import parse_pending_key

        parsed = parse_pending_key(pending_key)
        if not parsed:
            return
        kind, pid = parsed
        if kind == "skill_draft":
            self._pending_skill_drafts.pop(pid, None)
        elif kind == "model_snap":
            self._pending_model_snapshots.pop(pid, None)

    def _register_card_pending(self, card_id: str, pending_key: str, card: ConfirmationCard) -> None:
        self._card_to_pending[card_id] = pending_key
        if isinstance(card.context, dict):
            card.context["pending_key"] = pending_key

    def _pop_card_pending_key(self, card_id: str) -> str | None:
        return self._card_to_pending.pop(card_id, None)

    def _on_skill_draft_card_response(self, response: Any) -> None:
        if not isinstance(response, CardResponse):
            return
        cid = response.card_id
        pk = self._pop_card_pending_key(cid)
        if not pk or not pk.startswith("skill_draft:"):
            return
        draft_id = pk.split(":", 1)[1]
        sel = response.selected_option_id
        if sel == "confirm_create_skill":
            self.handle_skill_confirmation(draft_id, True)
        elif sel == "discard_skill_draft":
            self.handle_skill_confirmation(draft_id, False)

    def _on_model_confirm_card_response(self, response: Any) -> None:
        if not isinstance(response, CardResponse):
            return
        cid = response.card_id
        pk = self._pop_card_pending_key(cid)
        if not pk or not pk.startswith("model_snap:"):
            return
        snap_id = pk.split(":", 1)[1]
        self.handle_model_snapshot_confirmation(snap_id, response.selected_option_id)

    def handle_skill_confirmation(self, draft_id: str, confirmed: bool) -> dict[str, Any]:
        draft = self._pending_skill_drafts.pop(draft_id, None)
        if not draft:
            return {"ok": False, "error": "draft_not_found"}
        if not confirmed:
            _LOG.info("[SkillDraft] discarded draft_id=%s", draft_id)
            return {"ok": True, "discarded": True}
        try:
            from uap.skill.skill_store import SkillStore

            skill = draft["skill"]
            store = SkillStore(str(self._store.root))
            path = store.save_skill(skill)
            _LOG.info("[SkillDraft] saved skill_id=%s path=%s", skill.skill_id, path)
            return {"ok": True, "skill_id": skill.skill_id, "path": path}
        except Exception as e:
            _LOG.exception("[SkillDraft] save failed: %s", e)
            return {"ok": False, "error": str(e)}

    def handle_model_snapshot_confirmation(self, snapshot_id: str, selected_option_id: str) -> dict[str, Any]:
        snap = self._pending_model_snapshots.pop(snapshot_id, None)
        if not snap:
            return {"ok": False, "error": "snapshot_not_found"}
        project_id = str(snap.get("project_id") or "")
        if selected_option_id in ("cancel", "edit"):
            _LOG.info("[ModelSnap] user %s snapshot_id=%s", selected_option_id, snapshot_id)
            return {"ok": True, "discarded": True, "action": selected_option_id}
        if selected_option_id != "confirm":
            return {"ok": False, "error": "unknown_option"}

        try:
            project = self._store.get_project(project_id)
            if not project:
                return {"ok": False, "error": "project_not_found"}
            raw = snap.get("model_dict")
            if not isinstance(raw, dict):
                return {"ok": False, "error": "invalid_snapshot"}
            model = SystemModel(**raw)
            project.system_model = model
            project.status = ProjectStatus.MODELING
            project = self._store.update_project(project)
            self._save_system_model_file(project_id, model)

            out: dict[str, Any] = {"ok": True, "saved": True, "model_id": model.id}
            if snap.get("defer_skill_solidification") and snap.get("skill_session_dump"):
                skill_out = self._finalize_skill_after_model_confirm(
                    project_id=project_id,
                    project_name=str(snap.get("project_name") or project.name),
                    session_dump=snap["skill_session_dump"],
                    business_success=bool(snap.get("business_success")),
                )
                if skill_out:
                    out["solidified_skill"] = skill_out
            return out
        except Exception as e:
            _LOG.exception("[ModelSnap] persist failed: %s", e)
            return {"ok": False, "error": str(e)}

    def _finalize_skill_after_model_confirm(
        self,
        project_id: str,
        project_name: str,
        session_dump: dict[str, Any],
        business_success: bool,
    ) -> dict[str, Any] | None:
        if not getattr(self._cfg.agent, "modeling_skill_solidification_enabled", False):
            return None
        if not business_success:
            return None
        try:
            from uap.core.skills.models import SkillSession
            from uap.infrastructure.llm.factory import create_llm_chat_client
            from uap.skill.generator import SkillGenerator
            from uap.skill.skill_store import SkillStore

            session = SkillSession.model_validate(session_dump)
            llm = create_llm_chat_client(self._cfg.llm)
            gen = SkillGenerator(llm)
            project_info = {"project_id": project_id, "id": project_id, "name": project_name}
            skill = gen.generate(session, project_info)
            if not skill:
                return None
            cm = self._api_card_manager
            if cm is None:
                store = SkillStore(str(self._store.root))
                path = store.save_skill(skill)
                return {"skill_id": skill.skill_id, "path": path, "auto_saved": True}
            draft_id = f"skill_draft_{session.session_id}_{int(datetime.now().timestamp())}"
            self._pending_skill_drafts[draft_id] = {
                "skill": skill,
                "project_id": project_id,
                "session_id": session.session_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            card = self._build_skill_confirm_card(draft_id, skill, project_id)
            cm.create_card(card)
            pk = pending_skill_draft_key(draft_id)
            self._register_card_pending(card.card_id, pk, card)
            return {
                "skill_draft_id": draft_id,
                "pending_confirmation": True,
                "card_id": card.card_id,
                "card": card.to_dict(),
            }
        except Exception as e:
            _LOG.warning("[ModelSnap] post-confirm skill gen failed: %s", e)
            return None

    def _build_skill_confirm_card(self, draft_id: str, skill: Any, project_id: str) -> ConfirmationCard:
        triggers = getattr(skill, "trigger_conditions", None) or []
        if not isinstance(triggers, list):
            triggers = []
        preview = triggers[:3]
        params = getattr(skill, "parameters", None) or []
        param_names = [getattr(p, "name", str(p)) for p in params[:12]]

        lines = [
            f"**{getattr(skill, 'name', '技能')}**",
            "",
            f"- 触发条件示例：{', '.join(preview) if preview else '（未列出）'}",
            f"- 参数：{', '.join(param_names) if param_names else '无'}",
            "",
            (getattr(skill, "description", "") or "")[:1200],
        ]
        content = "\n".join(lines)
        return ConfirmationCard(
            card_id=f"skill_confirm_{draft_id}_{uuid.uuid4().hex[:8]}",
            card_type=CardType.SKILL_DRAFT_CONFIRM,
            title="确认保存生成的技能",
            content=content,
            options=[
                CardOption(id="confirm_create_skill", label="确认创建", description="写入技能库"),
                CardOption(id="discard_skill_draft", label="放弃", description="丢弃本次草稿"),
            ],
            priority=CardPriority.HIGH,
            context={
                "project_id": project_id,
                "draft_id": draft_id,
            },
        )

    def refresh_extractor(self):
        """重新创建提取器以使用最新配置"""
        from uap.infrastructure.llm.model_extractor import ModelExtractor

        try:
            llm_client = create_llm_chat_client(self._cfg.llm)
            self._extractor = ModelExtractor(llm_client)
            _LOG.info("Extractor refreshed with model=%s", self._cfg.llm.model)
        except ValueError as e:
            _LOG.warning("Extractor 未刷新（配置不完整）: %s", e)
    
    @property
    def store(self) -> ProjectStore:
        """获取项目存储"""
        return self._store
    
    @property
    def extractor(self) -> ModelExtractor:
        """获取模型提取器"""
        return self._extractor
    
    def set_extractor(self, extractor: ModelExtractor):
        """
        设置模型提取器
        
        Args:
            extractor: 新的模型提取器实例
        """
        self._extractor = extractor
    
    # ============ 项目管理 ============
    
    def create_project(
        self,
        name: str,
        description: str = "",
        workspace: str = ""
    ) -> dict:
        """
        创建新项目
        
        Args:
            name: 项目名称
            description: 项目描述
            workspace: 工作空间路径
            
        Returns:
            dict: 创建结果，包含project和project_id
        """
        if not name.strip():
            return {"ok": False, "error": "项目名称不能为空"}
        
        project = self._store.create_project(
            name=name.strip(),
            description=description.strip(),
            workspace=workspace.strip()
        )
        
        _LOG.info("创建项目: %s (id=%s)", project.name, project.id)
        
        return {
            "ok": True,
            "project": project.to_summary(),
            "project_id": project.id,
        }
    
    def get_project(self, project_id: str) -> dict:
        """
        获取项目信息
        
        Args:
            project_id: 项目ID
            
        Returns:
            dict: 项目信息和系统模型
        """
        try:
            project = self._store.get_project(project_id)
            return {
                "ok": True,
                "project": project.model_dump(),
                "system_model": project.system_model.model_dump() if project.system_model else None,
            }
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
    
    def list_projects(self) -> list[dict]:
        """
        列出所有项目
        
        Returns:
            list[dict]: 项目摘要列表
        """
        projects = self._store.list_projects()
        return [p.to_summary() for p in projects]
    
    def search_projects(self, query: str) -> list[dict]:
        """
        搜索项目
        
        Args:
            query: 搜索关键词
            
        Returns:
            list[dict]: 匹配的项目列表
        """
        projects = self._store.search_projects(query)
        return [p.to_summary() for p in projects]
    
    def delete_project(self, project_id: str) -> dict:
        """
        删除项目
        
        Args:
            project_id: 项目ID
            
        Returns:
            dict: 删除结果
        """
        try:
            self._store.delete_project(project_id)
            _LOG.info("删除项目: %s", project_id)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def update_project(
        self,
        project_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> dict:
        """
        更新项目信息
        
        Args:
            project_id: 项目ID
            name: 新名称
            description: 新描述
            tags: 新标签
            
        Returns:
            dict: 更新结果
        """
        try:
            project = self._store.get_project(project_id)
            if name is not None:
                project.name = name.strip()
            if description is not None:
                project.description = description.strip()
            if tags is not None:
                project.tags = tags
            
            project = self._store.update_project(project)
            return {"ok": True, "project": project.to_summary()}
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
    
    # ============ 系统模型 ============
    
    def save_model(self, project_id: str, model: SystemModel) -> dict:
        """
        保存系统模型
        
        Args:
            project_id: 项目ID
            model: 系统模型对象
            
        Returns:
            dict: 保存结果
        """
        try:
            project = self._store.get_project(project_id)
            project.system_model = model
            project = self._store.update_project(project)
            self._save_system_model_file(project_id, model)
            _LOG.info("保存模型: project=%s, model_id=%s", project_id, model.id)
            return {"ok": True, "model_id": model.id}
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
    
    def load_model(self, project_id: str) -> dict:
        """
        加载系统模型
        
        Args:
            project_id: 项目ID
            
        Returns:
            dict: 模型数据
        """
        model = self._store.load_model(project_id)
        if model is None:
            return {"ok": False, "error": "模型不存在"}
        return {"ok": True, "model": model.model_dump()}
    
    def extract_model_from_conversation(
        self,
        project_id: str,
        messages: list[dict],
        user_prompt: str,
    ) -> dict:
        """
        从对话中提取系统模型
        
        使用LLM分析对话历史和用户描述，自动提取系统的数学模型。
        
        Args:
            project_id: 项目ID
            messages: 对话历史消息列表
            user_prompt: 用户当前的系统描述
            
        Returns:
            dict: 提取结果，包含模型数据
        """
        try:
            project = self._store.get_project(project_id)
            
            _LOG.info("开始从对话提取模型: project=%s", project_id)
            
            # 调用LLM提取模型
            result = self._extractor.extract_from_conversation(
                messages=messages,
                user_prompt=user_prompt
            )
            
            if not result.success:
                _LOG.warning("模型提取失败: %s", result.error)
                return {
                    "ok": False,
                    "error": result.error or "模型提取失败"
                }
            
            model = result.model
            model.name = f"{project.name} - 对话建模"
            model.source = ModelSource.LLM_EXTRACTED
            model.modeling_prompt = user_prompt
            
            # 验证模型
            is_valid, errors = self._extractor.validate_model(model)
            if not is_valid:
                _LOG.warning("模型验证失败: %s", errors)
                return {
                    "ok": False,
                    "error": f"模型验证失败: {', '.join(errors)}"
                }
            
            # 保存模型和项目
            project.system_model = model
            project.status = ProjectStatus.MODELING
            project = self._store.update_project(project)
            self._save_system_model_file(project_id, model)
            
            _LOG.info(
                "模型提取成功: project=%s, variables=%d, relations=%d, confidence=%.2f",
                project_id, len(model.variables), len(model.relations), model.confidence
            )
            
            return {
                "ok": True,
                "model": model.model_dump(),
                "reasoning": result.reasoning,
                "message": f"成功提取模型，包含{len(model.variables)}个变量和{len(model.relations)}个关系"
            }
            
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
        except Exception as e:
            _LOG.error("模型提取异常: %s", str(e))
            return {"ok": False, "error": f"模型提取异常: {str(e)}"}
    
    def import_model_from_document(
        self,
        project_id: str,
        document_content: str,
        document_name: str = "",
    ) -> dict:
        """
        从文档导入系统模型
        
        使用LLM分析文档内容，自动提取系统的数学模型。
        
        Args:
            project_id: 项目ID
            document_content: 文档文本内容
            document_name: 文档名称
            
        Returns:
            dict: 提取结果，包含模型数据
        """
        try:
            project = self._store.get_project(project_id)
            
            _LOG.info(
                "开始从文档提取模型: project=%s, doc=%s",
                project_id, document_name
            )
            
            # 调用LLM提取模型
            result = self._extractor.extract_from_document(
                document_content=document_content,
                document_name=document_name
            )
            
            if not result.success:
                _LOG.warning("文档模型提取失败: %s", result.error)
                return {
                    "ok": False,
                    "error": result.error or "文档模型提取失败"
                }
            
            model = result.model
            model.name = f"{project.name} - 文档导入"
            model.source = ModelSource.LLM_EXTRACTED
            model.modeling_prompt = f"文档: {document_name}"
            
            # 验证模型
            is_valid, errors = self._extractor.validate_model(model)
            if not is_valid:
                _LOG.warning("模型验证失败: %s", errors)
                return {
                    "ok": False,
                    "error": f"模型验证失败: {', '.join(errors)}"
                }
            
            # 保存模型和项目
            project.system_model = model
            project.status = ProjectStatus.MODELING
            project = self._store.update_project(project)
            self._save_system_model_file(project_id, model)
            
            _LOG.info(
                "文档模型提取成功: project=%s, variables=%d, relations=%d",
                project_id, len(model.variables), len(model.relations)
            )
            
            return {
                "ok": True,
                "model": model.model_dump(),
                "reasoning": result.reasoning,
                "message": f"成功从文档'{document_name}'提取模型"
            }
            
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
        except Exception as e:
            _LOG.error("文档模型提取异常: %s", str(e))
            return {"ok": False, "error": f"文档模型提取异常: {str(e)}"}
    
    # ============ 预测配置 ============
    
    def save_prediction_config(
        self,
        project_id: str,
        config: PredictionConfig,
    ) -> dict:
        """
        保存预测配置
        
        Args:
            project_id: 项目ID
            config: 预测配置对象
            
        Returns:
            dict: 保存结果
        """
        try:
            project = self._store.get_project(project_id)
            project.prediction_config = config
            project = self._store.update_project(project)
            self._store.save_prediction_config(project_id, config)
            _LOG.info(
                "保存预测配置: project=%s, frequency=%ds, horizon=%ds",
                project_id, config.frequency_sec, config.horizon_sec
            )
            return {"ok": True}
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
    
    def load_prediction_config(self, project_id: str) -> dict:
        """
        加载预测配置
        
        Args:
            project_id: 项目ID
            
        Returns:
            dict: 配置数据
        """
        config = self._store.load_prediction_config(project_id)
        return {"ok": True, "config": config.model_dump()}
    
    # ============ 对话 ============
    
    def get_messages(self, project_id: str) -> list[dict]:
        """
        获取对话消息
        
        Args:
            project_id: 项目ID
            
        Returns:
            list[dict]: 消息列表
        """
        return self._store.load_messages(project_id)
    
    def save_message(
        self,
        project_id: str,
        role: str,
        content: str,
    ) -> dict:
        """
        保存对话消息
        
        Args:
            project_id: 项目ID
            role: 消息角色（user/assistant）
            content: 消息内容
            
        Returns:
            dict: 保存结果
        """
        try:
            messages = self._store.load_messages(project_id)
            messages.append({
                "role": role,
                "content": content,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            self._store.save_messages(project_id, messages)
            return {"ok": True, "message_count": len(messages)}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def append_assistant_message(self, project_id: str, content: str) -> dict:
        """
        追加助手消息
        
        Args:
            project_id: 项目ID
            content: 助手回复内容
            
        Returns:
            dict: 保存结果
        """
        return self.save_message(project_id, "assistant", content)
    
    def clear_messages(self, project_id: str) -> dict:
        """
        清空对话历史
        
        Args:
            project_id: 项目ID
            
        Returns:
            dict: 清空结果
        """
        try:
            self._store.save_messages(project_id, [])
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ============ ReAct / Plan 智能建模 ============

    def _modeling_context_dict(self, project_id: str, project) -> dict[str, object]:
        existing = (
            project.system_model.model_dump() if project.system_model else None
        )
        out: dict[str, object] = {
            "project_id": project_id,
            "project_name": project.name,
            "existing_model": existing,
            "system_model": format_system_model_for_prompt(project.system_model)
            if project.system_model
            else "",
        }
        try:
            agg = self._store.load_dst_aggregate(project_id)
        except OSError:
            agg = None
        if isinstance(agg, dict):
            vars_ = agg.get("variables") or []
            rels = agg.get("relations") or []
            if vars_ or rels:
                vpart = ",".join(str(x) for x in vars_[:20])
                if len(vars_) > 20:
                    vpart += "…"
                rpart = ",".join(str(x) for x in rels[:12])
                if len(rels) > 12:
                    rpart += "…"
                out["project_dst_aggregate_hint"] = (
                    f"（跨会话 DST 摘要：阶段={agg.get('current_stage')}，"
                    f"变量键={vpart}，关系键={rpart}）"
                )
        if getattr(self._cfg.memory, "graph_enabled", True):
            try:
                eg = self._store.load_entity_graph(project_id)
            except OSError:
                eg = None
            if isinstance(eg, dict) and (eg.get("nodes") or eg.get("edges")):
                nn = len(eg.get("nodes") or [])
                ne = len(eg.get("edges") or [])
                rels = [
                    str(e.get("relation_name") or "")
                    for e in (eg.get("edges") or [])[:12]
                ]
                rels = [x for x in rels if x]
                tail = "，".join(rels[:6])
                if len(rels) > 6:
                    tail += "…"
                out["entity_graph_hint"] = (
                    f"（实体关系图摘要：节点={nn}，有向边={ne}"
                    + (f"，关系名示例：{tail}" if tail else "")
                    + "）"
                )
        from pathlib import Path as _Path

        _pd = _Path(project.folder_path or project.workspace or "")
        if not str(_pd) or not _pd.is_dir():
            _pd = user_workspace_dir(project_id)
            _pd.mkdir(parents=True, exist_ok=True)
        if not _pd.is_dir():
            try:
                _pd = self._store.resolve_project_directory(project_id)
            except FileNotFoundError:
                _pd = user_workspace_dir(project_id)
                _pd.mkdir(parents=True, exist_ok=True)
        if _pd.is_dir():
            out["project_workspace"] = str(_pd.resolve())
        return out

    def _sync_entity_graph_if_enabled(self, project_id: str, model: Optional[SystemModel]) -> None:
        """``memory.graph_enabled`` 为真时，将 ``SystemModel`` 投影为 ``entity_graph.json``。"""
        if not getattr(self._cfg.memory, "graph_enabled", True):
            return
        if not model:
            return
        try:
            from uap.project.entity_graph import build_entity_graph_payload

            payload = build_entity_graph_payload(project_id, model)
            self._store.save_entity_graph(project_id, payload)
        except OSError as e:
            _LOG.warning("[EntityGraph] save failed project=%s: %s", project_id, e)

    def _save_system_model_file(self, project_id: str, model: SystemModel) -> None:
        """写入 ``model.json`` 并按配置同步实体图。"""
        self._store.save_model(project_id, model)
        self._sync_entity_graph_if_enabled(project_id, model)

    def _decide_mode_by_task(self, task: str, context: dict, chat_model) -> str:
        """返回 ``react`` 或 ``plan``（Auto 模式用）。"""
        text = task or ""
        tlo = text.lower()
        plan_kw_cn = ("步骤", "计划", "流程", "先", "然后", "接着", "最后", "第1", "第2")
        plan_kw_en = ("step", "first", "then", "next", "finally")
        if any(kw in text for kw in plan_kw_cn) or any(kw in tlo for kw in plan_kw_en):
            _LOG.info("[ModeDecision] Keyword heuristic -> plan")
            return "plan"
        from langchain_core.messages import HumanMessage

        from uap.infrastructure.llm.response_text import assistant_text_from_chat_response

        prompt = (
            "你是一个任务分类助手。请判断以下用户任务更适合哪种执行模式：\n"
            "- ReAct：需要灵活探索、多步推理，中间步骤可能动态调整。\n"
            "- Plan：目标明确，可预先分解为较固定的执行步骤。\n\n"
            f"用户任务：{task}\n\n请只回答一个单词：react 或 plan。"
        )
        try:
            resp = chat_model.invoke([HumanMessage(content=prompt)])
            answer = assistant_text_from_chat_response(resp).strip().lower()
            if "plan" in answer:
                _LOG.info("[ModeDecision] LLM decided -> plan")
                return "plan"
            _LOG.info("[ModeDecision] LLM decided -> react")
            return "react"
        except Exception as e:
            _LOG.warning("[ModeDecision] LLM failed, fallback react: %s", e)
            return "react"

    def _plan_step_to_react_step_dict(self, step) -> dict:
        """将 ``PlanStep`` 转为与 ``ReactStep.model_dump()`` 字段对齐的字典。"""
        from uap.plan.plan_agent import PlanStep, StepStatus

        if not isinstance(step, PlanStep):
            step = PlanStep.model_validate(step)
        dur_ms = 0
        if step.start_time is not None and step.end_time is not None:
            dur_ms = max(0, int((step.end_time - step.start_time) * 1000))
        is_err = step.status == StepStatus.FAILED
        return {
            "step_id": step.step_id,
            "thought": f"计划步骤: {step.description}",
            "action": (step.tool_name or "").strip() or "plan_step",
            "action_input": dict(step.tool_params or {}),
            "observation": step.observation or "",
            "is_error": is_err,
            "error_message": step.error,
            "duration_ms": dur_ms,
        }

    def _run_react_modeling(
        self,
        project_id: str,
        user_message: str,
        project,
        chat_model,
        context: dict,
        card_manager=None,
        web_search_func=None,
    ) -> dict:
        from pathlib import Path

        from uap.react import (
            DstManager,
            ReactAgent,
            ReactCardIntegration,
            create_web_search_skill,
        )
        from uap.react.file_access_skill import create_file_access_skill
        from uap.react.project_kb_skill import create_search_knowledge_skill
        from uap.skill.atomic_implemented import build_modeling_atomic_registry

        _LOG.info("[Modeling/ReAct] project=%s msg=%s", project_id, user_message[:50])
        dst_manager = DstManager()

        proj_dir = Path(project.folder_path or project.workspace or "")
        if not str(proj_dir) or not proj_dir.is_dir():
            proj_dir = user_workspace_dir(project_id)
            proj_dir.mkdir(parents=True, exist_ok=True)
        if not proj_dir.is_dir():
            proj_dir = self._store.resolve_project_directory(project_id)

        ask_only = bool(context.get("ask_mode_safe_tools_only"))
        if ask_only:
            from uap.application.ask_mode_registry import build_ask_mode_skills_registry

            skills_registry = build_ask_mode_skills_registry(
                project_id=project_id,
                proj_dir=proj_dir,
                cfg=self._cfg,
                knowledge=self._knowledge,
                web_search_func=web_search_func,
                create_file_access_skill=create_file_access_skill,
                create_web_search_skill=create_web_search_skill,
                create_search_knowledge_skill=create_search_knowledge_skill,
            )
        else:
            skills_registry = dict(build_modeling_atomic_registry())
            if web_search_func:
                skills_registry["web_search"] = create_web_search_skill(web_search_func)
            skills_registry["extract_model"] = self._create_model_extraction_skill()
            skills_registry["define_variable"] = self._create_variable_definition_skill()
            skills_registry["discover_relations"] = self._create_relation_discovery_skill()

            skills_registry["file_access"] = create_file_access_skill(project_folder=str(proj_dir))

            if getattr(self._cfg.agent, "modeling_win11_fs_skills_enabled", True):
                from uap.react.win11_project_fs_skills import create_win11_project_fs_skill_bundle

                skills_registry.update(create_win11_project_fs_skill_bundle(str(proj_dir)))

            if getattr(self._cfg.agent, "modeling_win_cli_skills_enabled", True) and sys.platform.startswith(
                "win"
            ):
                from uap.react.win_cli_skills import create_win_cli_skill_bundle

                skills_registry.update(create_win_cli_skill_bundle(str(proj_dir)))

            if getattr(self._cfg.agent, "modeling_kb_tool_enabled", True):
                skills_registry["search_knowledge"] = create_search_knowledge_skill(
                    project_id, self._knowledge
                )

        react_max_time = float(getattr(self._cfg.agent, "react_max_time_seconds", 300.0) or 300.0)
        max_ask_user = int(getattr(self._cfg.agent, "react_max_ask_user_per_turn", 1) or 1)
        max_ask_user = max(1, min(20, max_ask_user))
        react_max_steps = int(getattr(self._cfg.agent, "react_max_steps_default", 8) or 8)
        react_max_steps = max(1, min(32, react_max_steps))
        react_agent = ReactAgent(
            chat_model=chat_model,
            skills_registry=skills_registry,
            dst_manager=dst_manager,
            max_iterations=react_max_steps,
            max_time_seconds=react_max_time,
            max_ask_user_per_turn=max_ask_user,
            compression_config=self._cfg.context_compression,
            knowledge_service=self._knowledge,
        )
        card_integration = ReactCardIntegration(card_manager) if card_manager else None

        result = react_agent.run(user_message, context)
        _LOG.info("[Modeling/ReAct] done success=%s steps=%d", result.success, result.total_steps)

        sched = bool(context.get("scheduled_task_mode"))

        model = self._build_model_from_dst(dst_manager, result.session_id, project.name)
        substantive = self._modeling_snapshot_substantive(model)
        business_success = self._business_modeling_success(result.success, substantive)

        pending_ask_user_card: dict | None = None
        if (
            card_manager
            and result.pending_user_input
            and result.steps
            and result.steps[-1].action == "ask_user"
            and not result.steps[-1].is_error
        ):
            last = result.steps[-1]
            ttl = int(getattr(self._cfg.agent, "ask_user_card_timeout_seconds", 120) or 120)
            ttl = max(10, min(900, ttl))
            ask_card = build_ask_user_confirmation_card(
                project_id,
                result.session_id,
                last.step_id,
                dict(last.action_input or {}),
                expires_in_seconds=ttl,
            )
            card_manager.create_card(ask_card)
            pending_ask_user_card = ask_card.to_dict()

        pending_card: str | None = None
        pending_model_confirm_card: dict | None = None
        defer_model_confirm = bool(
            model and card_integration and card_manager and is_modeling_dst_complete(model)
        )

        session_obj = dst_manager.get_session(result.session_id)
        session_dump = session_obj.model_dump() if session_obj else None

        if defer_model_confirm:
            snap_id = uuid.uuid4().hex
            self._pending_model_snapshots[snap_id] = {
                "model_dict": model.model_dump() if model else {},
                "project_id": project_id,
                "project_name": project.name,
                "session_id": result.session_id,
                "skill_session_dump": session_dump,
                "business_success": business_success,
                "defer_skill_solidification": bool(
                    getattr(self._cfg.agent, "modeling_skill_solidification_enabled", False)
                    and business_success
                ),
            }
            pending_card = card_integration.create_model_confirm_card(
                session_id=result.session_id,
                project_id=project_id,
                variables=[v.model_dump() for v in model.variables],
                relations=[r.model_dump() for r in model.relations],
                constraints=model.constraints or [],
            )
            if pending_card and card_manager:
                crd = card_manager.get_card(pending_card)
                if crd:
                    pk = pending_model_snap_key(snap_id)
                    self._register_card_pending(pending_card, pk, crd)
                    pending_model_confirm_card = crd.to_dict()
        elif model:
            project.system_model = model
            project.status = ProjectStatus.MODELING
            project = self._store.update_project(project)
            self._save_system_model_file(project_id, model)

        out = {
            "ok": True,
            "message": self._generate_response_message(result, model),
            "model": model.model_dump() if model else None,
            "session_id": result.session_id,
            "steps": [s.model_dump() for s in result.steps],
            "dst_state": result.dst_state,
            "pending_card": pending_card,
            "pending_model_confirm_card": pending_model_confirm_card,
            "model_persist_deferred": bool(defer_model_confirm),
            "pending_ask_user_card": pending_ask_user_card,
            "success": result.success,
            "modeling_substantive": substantive,
            "business_success": business_success,
            "pending_user_input": result.pending_user_input,
            "tool_calls": result.tool_calls,
            "stop_reason": _modeling_stop_reason(result.error_message),
        }
        if not sched:
            self._persist_dst_project_aggregate(project_id, dst_manager)
        if not defer_model_confirm and not sched:
            sol = self._maybe_generate_skill_draft_and_request_confirmation(
                project_id,
                project.name,
                dst_manager,
                result.session_id,
                business_success,
                card_manager,
            )
            if sol:
                out["solidified_skill"] = sol
        return out

    def _run_plan_modeling(
        self,
        project_id: str,
        user_message: str,
        project,
        chat_model,
        context: dict,
        card_manager=None,
        web_search_func=None,
    ) -> dict:
        from pathlib import Path

        from uap.plan import PlanAgent
        from uap.react import DstManager, ReactCardIntegration, create_web_search_skill
        from uap.react.file_access_skill import create_file_access_skill
        from uap.react.project_kb_skill import create_search_knowledge_skill
        from uap.skill.atomic_implemented import build_modeling_atomic_registry

        _LOG.info("[Modeling/Plan] project=%s", project_id)
        sched = bool(context.get("scheduled_task_mode"))
        dst_manager = DstManager()
        skills_registry: dict = dict(build_modeling_atomic_registry())
        if web_search_func:
            skills_registry["web_search"] = create_web_search_skill(web_search_func)
        skills_registry["extract_model"] = self._create_model_extraction_skill()
        skills_registry["define_variable"] = self._create_variable_definition_skill()
        skills_registry["discover_relations"] = self._create_relation_discovery_skill()

        proj_dir = Path(project.folder_path or project.workspace or "")
        if not str(proj_dir) or not proj_dir.is_dir():
            proj_dir = user_workspace_dir(project_id)
            proj_dir.mkdir(parents=True, exist_ok=True)
        if not proj_dir.is_dir():
            proj_dir = self._store.resolve_project_directory(project_id)
        skills_registry["file_access"] = create_file_access_skill(project_folder=str(proj_dir))

        if getattr(self._cfg.agent, "modeling_win11_fs_skills_enabled", True):
            from uap.react.win11_project_fs_skills import create_win11_project_fs_skill_bundle

            skills_registry.update(create_win11_project_fs_skill_bundle(str(proj_dir)))

        if getattr(self._cfg.agent, "modeling_win_cli_skills_enabled", True) and sys.platform.startswith(
            "win"
        ):
            from uap.react.win_cli_skills import create_win_cli_skill_bundle

            skills_registry.update(create_win_cli_skill_bundle(str(proj_dir)))

        if getattr(self._cfg.agent, "modeling_kb_tool_enabled", True):
            skills_registry["search_knowledge"] = create_search_knowledge_skill(
                project_id, self._knowledge
            )

        plan_max_time = float(getattr(self._cfg.agent, "plan_max_time_seconds", 300.0) or 300.0)
        plan_agent = PlanAgent(
            chat_model=chat_model,
            skills_registry=skills_registry,
            dst_manager=dst_manager,
            max_replans=3,
            max_time_seconds=plan_max_time,
            enable_parallel=False,
        )
        card_integration = ReactCardIntegration(card_manager) if card_manager else None

        result = plan_agent.run(user_message, context)
        model = self._build_model_from_dst(dst_manager, result.session_id, project.name)
        substantive = self._modeling_snapshot_substantive(model)
        business_success = self._business_modeling_success(result.success, substantive)

        pending_card: str | None = None
        pending_model_confirm_card: dict | None = None
        defer_model_confirm = bool(
            model and card_integration and card_manager and is_modeling_dst_complete(model)
        )
        session_obj = dst_manager.get_session(result.session_id)
        session_dump = session_obj.model_dump() if session_obj else None

        if defer_model_confirm:
            snap_id = uuid.uuid4().hex
            self._pending_model_snapshots[snap_id] = {
                "model_dict": model.model_dump() if model else {},
                "project_id": project_id,
                "project_name": project.name,
                "session_id": result.session_id,
                "skill_session_dump": session_dump,
                "business_success": business_success,
                "defer_skill_solidification": bool(
                    getattr(self._cfg.agent, "modeling_skill_solidification_enabled", False)
                    and business_success
                ),
            }
            pending_card = card_integration.create_model_confirm_card(
                session_id=result.session_id,
                project_id=project_id,
                variables=[v.model_dump() for v in model.variables],
                relations=[r.model_dump() for r in model.relations],
                constraints=model.constraints or [],
            )
            if pending_card and card_manager:
                crd = card_manager.get_card(pending_card)
                if crd:
                    pk = pending_model_snap_key(snap_id)
                    self._register_card_pending(pending_card, pk, crd)
                    pending_model_confirm_card = crd.to_dict()
        elif model:
            project.system_model = model
            project.status = ProjectStatus.MODELING
            project = self._store.update_project(project)
            self._save_system_model_file(project_id, model)

        plan_dump = [p.model_dump() for p in result.plan]
        react_shaped = [self._plan_step_to_react_step_dict(p) for p in result.plan]
        tool_calls = sum(
            1
            for st in result.plan
            if st.tool_name
            and str(getattr(st.status, "value", st.status)) == "completed"
        )
        out = {
            "ok": True,
            "message": self._generate_response_message(result, model),
            "model": model.model_dump() if model else None,
            "session_id": result.session_id,
            "steps": react_shaped,
            "plan": plan_dump,
            "dst_state": result.dst_state,
            "pending_card": pending_card,
            "pending_model_confirm_card": pending_model_confirm_card,
            "model_persist_deferred": bool(defer_model_confirm),
            "success": result.success,
            "modeling_substantive": substantive,
            "business_success": business_success,
            "tool_calls": tool_calls,
            "replan_count": result.replan_count,
            "stop_reason": _modeling_stop_reason(result.error_message),
        }
        if not sched:
            self._persist_dst_project_aggregate(project_id, dst_manager)
        if not defer_model_confirm and not sched:
            sol = self._maybe_generate_skill_draft_and_request_confirmation(
                project_id,
                project.name,
                dst_manager,
                result.session_id,
                business_success,
                card_manager,
            )
            if sol:
                out["solidified_skill"] = sol
        return out

    def run_scheduled_auxiliary_flow(
        self,
        project_id: str,
        trigger_user_message: str,
        prediction_service: Any,
        *,
        web_search_func: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        """
        定时任务入口：意图/场景 + ``classified_scheduled_next``，再分支预测、ReAct/Plan 或跳过。
        不写入对话历史；调用方负责持久化预测结果或按需追加助手消息。
        """
        msgs = self._store.load_messages(project_id)
        intent_scene = run_modeling_intent_scene_if_enabled(
            self._cfg,
            msgs,
            trigger_user_message,
            mode_requested="scheduled",
        )
        nxt = str(intent_scene.get("classified_scheduled_next") or "prediction").strip().lower()
        if nxt not in ("prediction", "react", "plan", "none"):
            nxt = "prediction"

        out_base: dict[str, Any] = {
            "ok": True,
            "intent_scene": intent_scene,
            "scheduled_next": nxt,
        }

        if nxt == "none":
            out_base["branch"] = "none"
            return out_base

        if nxt == "prediction":
            proj = self._store.get_project(project_id)
            if not proj:
                return {"ok": False, "error": "项目不存在", "scheduled_next": nxt}
            result = prediction_service.run_prediction(proj, proj.prediction_config)
            out_base["branch"] = "prediction"
            out_base["prediction_result"] = result
            return out_base

        task_agent = build_modeling_task_with_prior_dialogue(msgs, trigger_user_message)
        modeling_out = self.react_modeling(
            project_id,
            task_agent,
            card_manager=None,
            web_search_func=web_search_func,
            mode=nxt,
            intent_scene=intent_scene,
            original_user_message=trigger_user_message,
            scheduled_task_mode=True,
        )
        merged: dict[str, Any] = {**out_base, **modeling_out}
        merged["branch"] = nxt
        merged["intent_scene"] = intent_scene
        merged["scheduled_next"] = nxt
        return merged

    def react_modeling(
        self,
        project_id: str,
        user_message: str,
        card_manager=None,
        web_search_func=None,
        mode: str | None = None,
        intent_scene: dict | None = None,
        original_user_message: str | None = None,
        on_llm_token: Optional[Callable[[str], None]] = None,
        interrupt_handles: dict | None = None,
        deep_search_cot_mode: bool = False,
        scheduled_task_mode: bool = False,
    ) -> dict:
        """
        **RADH 智能建模主入口**：支持 ``react`` / ``plan`` / ``auto`` / ``ask``（``ask``=只读安全技能 ReAct）。

        Args:
            mode: ``react`` | ``plan`` | ``auto`` | ``ask``；为 ``None`` 或空时使用 ``UapConfig.agent.modeling_agent_mode``。
            original_user_message: 若 ``user_message`` 含拼接的历史对话，Auto 模式分类时用此原始句。
            on_llm_token: 可选；ReAct ``decide`` 中 LLM 流式输出时按文本片段回调（用于前端轮询拉流）。
            deep_search_cot_mode: 为真时注入 ``context["deep_search_cot_mode"]``，启用更深检索与显式思维链提示。
            scheduled_task_mode: 定时任务辅助模式：不注入项目 DST 聚合摘要、不持久化 DST 聚合、不挂卡片（HITL）。

        解析模式后会在 ``context`` 中写入 ``modeling_mode_requested``（``react``/``plan``/``auto``）
        与 ``modeling_mode_used``（本轮实际 ``react`` 或 ``plan``），供 ReAct/Plan 主提示与意图分类使用。
        """
        try:
            if scheduled_task_mode:
                card_manager = None
            project = self._store.get_project(project_id)
            chat_model = create_langchain_chat_model(self._cfg.llm)
            context = self._modeling_context_dict(project_id, project)
            if scheduled_task_mode:
                context["scheduled_task_mode"] = True
                context.pop("project_dst_aggregate_hint", None)
            if intent_scene:
                context.update(intent_scene)
            if on_llm_token is not None:
                context["_on_llm_token"] = on_llm_token
            if interrupt_handles:
                context["_interrupt"] = interrupt_handles
            if deep_search_cot_mode:
                context["deep_search_cot_mode"] = True
            _LOG.info(
                "[Modeling] deep_search_cot_mode=%s (context flag=%s)",
                bool(deep_search_cot_mode),
                bool(context.get("deep_search_cot_mode")),
            )

            raw = (mode if mode is not None else self._cfg.agent.modeling_agent_mode or "react")
            mode_requested = str(raw).strip().lower() or "react"
            if mode_requested not in ("auto", "react", "plan", "ask"):
                _LOG.warning("[Modeling] Unknown mode %r, using react", mode_requested)
                mode_requested = "react"

            mode_decision_line = (
                original_user_message
                if (original_user_message is not None and str(original_user_message).strip())
                else user_message
            )
            if mode_requested == "ask":
                mode_used = "ask"
                context["ask_mode_safe_tools_only"] = True
            elif mode_requested == "auto":
                mode_used = self._decide_mode_by_task(mode_decision_line, context, chat_model)
            else:
                mode_used = mode_requested

            _LOG.info(
                "[Modeling] start project=%s mode_requested=%s mode_used=%s",
                project_id,
                mode_requested,
                mode_used,
            )

            context["modeling_mode_requested"] = mode_requested
            context["modeling_mode_used"] = mode_used

            if mode_used == "plan":
                out = self._run_plan_modeling(
                    project_id,
                    user_message,
                    project,
                    chat_model,
                    context,
                    card_manager=card_manager,
                    web_search_func=web_search_func,
                )
            else:
                out = self._run_react_modeling(
                    project_id,
                    user_message,
                    project,
                    chat_model,
                    context,
                    card_manager=card_manager,
                    web_search_func=web_search_func,
                )
            out["mode_requested"] = mode_requested
            out["mode_used"] = mode_used
            return out
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
        except Exception as e:
            _LOG.exception("[Modeling] Error: %s", str(e))
            return {"ok": False, "error": f"建模异常: {str(e)}"}

    def plan_modeling(
        self,
        project_id: str,
        user_message: str,
        card_manager=None,
        web_search_func=None,
    ) -> dict:
        """兼容入口：等价于 ``react_modeling(..., mode='plan')``。"""
        return self.react_modeling(
            project_id,
            user_message,
            card_manager=card_manager,
            web_search_func=web_search_func,
            mode="plan",
        )

    def _create_model_extraction_skill(self):
        """创建模型提取技能"""
        from uap.skill.atomic_skills import AtomicSkill, SkillMetadata, SkillCategory, SkillComplexity

        metadata = SkillMetadata(
            skill_id="extract_model",
            name="提取系统模型",
            description=(
                "在用户已提供足够信息时，从其自然语言目标中抽取变量、关系与约束；"
                "若用户只有一句话目标，应先通过对话或 ask_user 补全后再调用"
            ),
            category=SkillCategory.MODELING,
            subcategory="extraction",
            input_schema={
                "type": "object",
                "required": ["user_description"],
                "properties": {
                    "user_description": {
                        "type": "string",
                        "description": "用户目标与已知信息的合并叙述（可由多轮对话拼成，不必是专业长文）",
                    }
                },
            },
            estimated_time=10,
            complexity=SkillComplexity.MODERATE,
            provides_skills=["variable_collection", "relation_discovery"]
        )

        skill = AtomicSkill(metadata)

        def executor(s, user_description="", **kwargs):
            try:
                result = self._extractor.extract_from_conversation(
                    messages=[{"role": "user", "content": user_description}],
                    user_prompt=user_description
                )
                if result.success:
                    model = result.model
                    return {
                        "observation": f"提取到模型：{len(model.variables)}个变量，{len(model.relations)}个关系",
                        "variables": [v.model_dump() for v in model.variables],
                        "relations": [r.model_dump() for r in model.relations],
                    }
                else:
                    return {"error": result.error, "observation": f"提取失败: {result.error}"}
            except Exception as e:
                return {"error": str(e), "observation": f"提取异常: {str(e)}"}

        skill.set_executor(executor)
        return skill

    def _create_variable_definition_skill(self):
        """创建变量定义技能"""
        from uap.skill.atomic_skills import AtomicSkill, SkillMetadata, SkillCategory, SkillComplexity

        metadata = SkillMetadata(
            skill_id="define_variable",
            name="定义系统变量",
            description="为用户关心的预测对象补充或修正一个状态变量（名称、含义、单位等，可用日常用语）",
            category=SkillCategory.MODELING,
            subcategory="variable",
            input_schema={
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "description": "变量名称"},
                    "value_type": {"type": "string", "description": "变量类型"},
                    "description": {"type": "string", "description": "变量描述"},
                    "unit": {"type": "string", "description": "物理单位"},
                }
            },
            estimated_time=2,
            complexity=SkillComplexity.SIMPLE,
        )

        skill = AtomicSkill(metadata)

        def executor(s, name="", description="", value_type="float", unit="", **kwargs):
            var = Variable(
                name=name,
                value_type=value_type,
                description=description,
                unit=unit or "",
            )
            return {
                "observation": f"定义变量：{name} (类型={value_type})",
                "variable": var.model_dump(),
                "needs_confirmation": True,
            }

        skill.set_executor(executor)
        return skill

    def _create_relation_discovery_skill(self):
        """创建关系发现技能"""
        from uap.skill.atomic_skills import AtomicSkill, SkillMetadata, SkillCategory, SkillComplexity

        metadata = SkillMetadata(
            skill_id="discover_relations",
            name="发现系统关系",
            description="根据用户叙述，为已关注的变量补充一条关系或因果/相关说明（不必写方程）",
            category=SkillCategory.MODELING,
            subcategory="relation",
            input_schema={
                "type": "object",
                "required": ["from_var", "to_var", "relationship"],
                "properties": {
                    "from_var": {"type": "string", "description": "源变量"},
                    "to_var": {"type": "string", "description": "目标变量"},
                    "relationship": {"type": "string", "description": "关系描述"},
                }
            },
            estimated_time=5,
            complexity=SkillComplexity.MODERATE,
        )

        skill = AtomicSkill(metadata)

        def executor(s, from_var="", to_var="", relationship="", **kwargs):
            rel = Relation(
                name=f"{from_var}_to_{to_var}",
                description=relationship,
                relation_type="causal",
                cause_vars=[from_var] if from_var else [],
                effect_var=to_var or from_var or "unknown",
            )
            return {
                "observation": f"发现关系：{from_var} → {to_var}",
                "relation": rel.model_dump(),
                "needs_confirmation": True,
            }

        skill.set_executor(executor)
        return skill

    def _build_model_from_dst(self, dst_manager, session_id: str, project_name: str) -> Optional[SystemModel]:
        """从DST状态构建系统模型"""
        model_summary = dst_manager.get_model_summary(session_id)
        if not model_summary:
            return None

        variables = [Variable(**v) if isinstance(v, dict) else v for v in model_summary.get("variables", [])]
        relations = [Relation(**r) if isinstance(r, dict) else r for r in model_summary.get("relations", [])]

        model = SystemModel(
            id=str(uuid.uuid4()),
            name=f"{project_name} - ReAct建模",
            source=ModelSource.LLM_EXTRACTED,
            variables=variables,
            relations=relations,
            constraints=model_summary.get("constraints", []),
            confidence=model_summary.get("confidence", 0.5),
        )
        return model

    _MODELING_ERROR_HINTS: dict[str, str] = {
        "empty_plan": (
            "未能从模型输出中解析出有效的「计划步骤」JSON。"
            "请确认当前 LLM 是否按提示词返回 JSON 数组（含 description、tool_name、tool_params），"
            "或尝试换用更擅长遵循指令的模型后再试。"
        ),
        "timeout": (
            "本次会话已达到单次运行的最大时长，推理已停止。"
            "若智能体曾向您提问，请在**下一条消息**中直接作答或选择选项，以便继续建模。"
        ),
        "max_iterations": "已达到单次会话的最大推理步数上限，未完成建模。可精简目标或分多轮说明后再试。",
        "repeated_tool_failures": (
            "同一工具已连续多次失败，系统已停止本轮自动重试。"
            "请在下一条消息中说明数据文件位置、或确认项目目录下是否已有待分析文件。"
        ),
        "max_replans_exceeded": "计划多次重规划后仍失败，请检查任务描述或换用模型后重试。",
        "replan_empty": "重规划时模型未返回有效后续步骤，请调整表述或换用模型后重试。",
    }

    def _format_modeling_error_hint(self, code: Optional[str]) -> str:
        if not code:
            return "未知错误"
        return self._MODELING_ERROR_HINTS.get(code, f"（内部原因码：{code}）")

    def _append_last_ask_user_excerpt(self, result: Any, parts: list[str]) -> None:
        steps = getattr(result, "steps", None) or []
        for step in reversed(steps):
            action = getattr(step, "action", "") or ""
            if action != "ask_user":
                continue
            raw_inp = getattr(step, "action_input", None)
            inp: dict[str, Any] = dict(raw_inp) if isinstance(raw_inp, dict) else {}
            q = (inp.get("question") or "").strip()
            if not q:
                break
            cap = 500
            snippet = q if len(q) <= cap else q[: cap - 1] + "…"
            parts.append(f"智能体最后向您提出的问题：\n{snippet}")
            opts = inp.get("options")
            if isinstance(opts, list) and len(opts) > 0:
                parts.append(f"（共 {len(opts)} 个选项，您可在下一条消息中直接回复选择或补充说明。）")
            break

    def _persist_dst_project_aggregate(self, project_id: str, dst_manager: Any) -> None:
        if not (project_id or "").strip():
            return
        snap = dst_manager.export_project_aggregate_dict(project_id)
        if not snap:
            return
        try:
            self._store.save_dst_aggregate(project_id, snap)
        except OSError as e:
            _LOG.warning("[Modeling] save_dst_aggregate failed: %s", e)

    def _maybe_generate_skill_draft_and_request_confirmation(
        self,
        project_id: str,
        project_name: str,
        dst_manager: Any,
        session_id: str,
        business_success: bool,
        card_manager: Any = None,
    ) -> dict[str, Any] | None:
        if not getattr(self._cfg.agent, "modeling_skill_solidification_enabled", False):
            return None
        if not business_success or not (project_id or "").strip():
            return None
        session = dst_manager.get_session(session_id)
        if not session or not getattr(session, "project_id", ""):
            return None
        if session.project_id.strip() != project_id.strip():
            _LOG.warning("[Modeling] session project_id mismatch, skip skill solidification")
            return None
        if not session.actions:
            return None
        try:
            from uap.infrastructure.llm.factory import create_llm_chat_client
            from uap.skill.generator import SkillGenerator
            from uap.skill.skill_store import SkillStore

            llm = create_llm_chat_client(self._cfg.llm)
            gen = SkillGenerator(llm)
            project_info = {"project_id": project_id, "id": project_id, "name": project_name}
            skill = gen.generate(session, project_info)
            if not skill:
                return None
            if card_manager is None:
                store = SkillStore(str(self._store.root))
                path = store.save_skill(skill)
                return {"skill_id": skill.skill_id, "path": path, "auto_saved": True}

            draft_id = f"skill_draft_{session_id}_{int(datetime.now().timestamp())}"
            self._pending_skill_drafts[draft_id] = {
                "skill": skill,
                "project_id": project_id,
                "session_id": session_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            card = self._build_skill_confirm_card(draft_id, skill, project_id)
            card_manager.create_card(card)
            pk = pending_skill_draft_key(draft_id)
            self._register_card_pending(card.card_id, pk, card)
            return {
                "skill_draft_id": draft_id,
                "pending_confirmation": True,
                "card_id": card.card_id,
                "card": card.to_dict(),
            }
        except Exception as e:
            _LOG.warning("[Modeling] skill solidification failed: %s", e)
            return None

    @staticmethod
    def _modeling_snapshot_substantive(model: Optional[SystemModel]) -> bool:
        """是否已有可展示/可保存的结构化建模快照（变量、关系或约束）。"""
        if not model:
            return False
        if getattr(model, "variables", None):
            return len(model.variables) > 0
        if getattr(model, "relations", None):
            return len(model.relations) > 0
        cons = getattr(model, "constraints", None) or []
        return len(cons) > 0

    @staticmethod
    def _business_modeling_success(protocol_success: bool, substantive: bool) -> bool:
        """业务上可视为「本轮建模有实质进展」：协议正常结束且已有结构化快照。"""
        return bool(protocol_success) and bool(substantive)

    def _append_plan_failure_excerpt(self, result: Any, parts: list[str]) -> None:
        plan = getattr(result, "plan", None) or []
        if not plan:
            return
        lines: list[str] = []
        for p in plan[:10]:
            sid = getattr(p, "step_id", 0)
            desc = (getattr(p, "description", None) or "").strip()
            st = getattr(p, "status", None)
            stv = getattr(st, "value", st) if st is not None else ""
            if desc:
                lines.append(f"- 步骤{sid} [{stv}]: {desc[:140]}{'…' if len(desc) > 140 else ''}")
        if lines:
            parts.append("本会话内相关计划步骤摘要：\n" + "\n".join(lines))

    def _generate_response_message(self, result: Any, model: Optional[SystemModel]) -> str:
        """生成面向用户的响应消息（成功摘要 / 失败时中文说明 + 上下文摘录）。"""
        if getattr(result, "pending_user_input", False):
            parts = [
                "已向您提出问题，请在「下一条消息」中直接回复或选择选项，以便继续建模。"
            ]
            self._append_last_ask_user_excerpt(result, parts)
            return "\n\n".join(parts)

        if result.success:
            fo = getattr(result, "final_output", None)
            human = (
                isinstance(fo, str)
                and fo.strip()
                and fo.strip() != "任务完成"
            )
            model_parts: list[str] = []
            if model:
                if model.variables:
                    model_parts.append(f"已识别 {len(model.variables)} 个变量")
                if model.relations:
                    model_parts.append(f"发现 {len(model.relations)} 个关系")
                if model.constraints:
                    model_parts.append(f"已记录 {len(model.constraints)} 条约束")
            if human:
                base = str(fo).strip()
                if model_parts:
                    return base + "\n\n" + "建模进度：" + "，".join(model_parts) + "。"
                return base
            if model_parts:
                return "建模进度：" + "，".join(model_parts) + "。"
            return (
                "本轮推理已结束，但尚未沉淀出可保存的结构化变量、关系或约束。"
                "若需继续建模，请补充：预测对象、时间范围、数据文件/接口或上传文档。"
            )

        code = getattr(result, "error_message", None) or ""
        hint = self._format_modeling_error_hint(str(code).strip() or None)
        blocks: list[str] = [f"建模未能完成：{hint}"]

        self._append_last_ask_user_excerpt(result, blocks)
        self._append_plan_failure_excerpt(result, blocks)

        return "\n\n".join(blocks)
