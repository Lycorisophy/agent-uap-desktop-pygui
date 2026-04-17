"""项目、系统模型、建模对话 API。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from uap.project.models import ProjectStatus, SystemModel

from uap.interfaces.api._log import _LOG


class ProjectsApiMixin:
    def create_project(self, name: str, description: str = "") -> dict:
        """Create new project"""
        return self.project_service.create_project(name, description)

    def get_project(self, project_id: str) -> Optional[dict]:
        """Get project info"""
        if not project_id or project_id == "undefined":
            return None
        project = self.project_store.get_project(project_id)
        return project.model_dump() if project else None

    def list_projects(self, limit: int = 50, offset: int = 0) -> dict:
        """List all projects"""
        projects = self.project_store.list_projects()
        total = len(projects)
        items = projects[offset : offset + limit]
        return {
            "items": [p.to_summary() for p in items],
            "total": total,
        }

    def delete_project(self, project_id: str) -> dict:
        """Delete project"""
        if not project_id or project_id == "undefined":
            return {"success": False, "error": "Invalid project ID"}

        try:
            tasks = self.scheduler.get_project_tasks(project_id)
            for task in tasks:
                self.scheduler.remove_task(task.id)

            self.project_store.delete_project(project_id)
            return {"success": True, "project_id": project_id}
        except FileNotFoundError:
            return {"success": False, "error": "Project not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def save_model(self, project_id: str, model_data: dict) -> dict:
        """Save system model"""
        model = SystemModel(**model_data)
        self.project_store.save_model(project_id, model)

        project = self.project_store.get_project(project_id)
        if project:
            project.status = ProjectStatus.MODELING
            self.project_store.save_project(project)

        return {"success": True, "project_id": project_id}

    def get_model(self, project_id: str) -> Optional[dict]:
        """Get system model"""
        project = self.project_store.get_project(project_id)
        if project and project.system_model:
            return project.system_model.model_dump()
        return None

    def extract_model_from_conversation(
        self,
        project_id: str,
        messages: list[dict],
        user_prompt: str,
    ) -> dict:
        """Extract system model from conversation"""
        return self.project_service.extract_model_from_conversation(
            project_id, messages, user_prompt
        )

    def modeling_chat(self, project_id: str, message: str, mode: str | None = None) -> dict:
        """建模对话；``mode`` 为 ``auto`` / ``react`` / ``plan``，省略时使用配置 ``modeling_agent_mode``。"""
        _LOG.info(
            "[API] modeling_chat called: project_id=%s, message_len=%d, mode=%s",
            project_id,
            len(message),
            mode,
        )
        try:
            messages = self.project_store.load_messages(project_id)
            _LOG.debug("[API] Loaded %d existing messages", len(messages))

            messages.append(
                {
                    "role": "user",
                    "content": message,
                    "created_at": datetime.now().isoformat(),
                }
            )
            self.project_store.save_messages(project_id, messages)

            effective_mode = mode
            if effective_mode is None or not str(effective_mode).strip():
                effective_mode = self.config.agent.modeling_agent_mode or "react"

            result = self.project_service.react_modeling(
                project_id=project_id,
                user_message=message,
                card_manager=self.card_manager,
                web_search_func=self._get_web_search_func(),
                mode=str(effective_mode).strip().lower(),
            )
            _LOG.info(
                "[API] modeling result: ok=%s, success=%s, mode_used=%s",
                result.get("ok"),
                result.get("success"),
                result.get("mode_used"),
            )

            if result.get("ok"):
                response_message = result.get("message", "建模完成")

                steps_info = ""
                if result.get("steps"):
                    mu = (result.get("mode_used") or "").strip().lower()
                    mr = (result.get("mode_requested") or "").strip().lower()
                    if mr == "auto" and mu:
                        label = f"Auto→{mu}"
                    elif mu == "plan":
                        label = "Plan"
                    else:
                        label = "ReAct"
                    steps_info = f"\n\n[{label}执行: {len(result['steps'])}步]"
                    for step in result["steps"][-3:]:
                        if step.get("thought"):
                            steps_info += f"\n- 思考: {step['thought'][:50]}..."
                        if step.get("action") and step.get("action") != "FINAL_ANSWER":
                            steps_info += f"\n  行动: {step['action']}"
                        if step.get("description"):
                            steps_info += f"\n- 步骤: {step['description'][:60]}..."
                        if step.get("tool_name"):
                            steps_info += f"\n  工具: {step['tool_name']}"

                dst_info = ""
                dst_state = result.get("dst_state", {})
                if dst_state:
                    progress = dst_state.get("progress", 0)
                    stage = dst_state.get("current_stage", "unknown")
                    vars_count = len(dst_state.get("variables", []))
                    rels_count = len(dst_state.get("relations", []))
                    dst_info = (
                        f"\n[进度: {progress*100:.0f}%] 阶段={stage}, "
                        f"变量={vars_count}, 关系={rels_count}"
                    )

                full_message = response_message + steps_info + dst_info

                self.project_store.save_messages(
                    project_id,
                    self.project_store.load_messages(project_id)
                    + [
                        {
                            "role": "assistant",
                            "content": full_message,
                            "created_at": datetime.now().isoformat(),
                        }
                    ],
                )

                return {
                    "ok": True,
                    "message": full_message,
                    "model": result.get("model"),
                    "session_id": result.get("session_id"),
                    "steps": result.get("steps", []),
                    "dst_state": dst_state,
                    "pending_card": result.get("pending_card"),
                    "success": result.get("success", False),
                    "tool_calls": result.get("tool_calls", 0),
                    "mode_used": result.get("mode_used"),
                    "mode_requested": result.get("mode_requested"),
                    "plan": result.get("plan"),
                    "replan_count": result.get("replan_count", 0),
                }
            error_msg = result.get("error", "建模失败")
            _LOG.warning("[API] modeling_chat failed: %s", error_msg)
            return {"ok": False, "message": error_msg}
        except Exception as e:
            _LOG.exception("[API] modeling_chat exception: %s", str(e))
            return {"ok": False, "message": str(e)}

    def _get_web_search_func(self):
        """获取Web搜索函数"""
        return None

    def import_model_from_document(
        self,
        project_id: str,
        document_content: str,
        document_name: str,
    ) -> dict:
        """Import system model from document"""
        return self.project_service.import_model_from_document(
            project_id, document_content, document_name
        )
