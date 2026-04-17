"""项目、系统模型、建模对话 API。"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Optional

from uap.project.models import ProjectStatus, SystemModel

from uap.application.modeling_intent_classifier import (
    build_modeling_task_with_prior_dialogue,
    run_modeling_intent_scene_if_enabled,
)
from uap.infrastructure.modeling_stream_hub import run_in_thread
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
        _LOG.info(
            "[API] list_projects: root=%s total=%s returning=%s",
            self.project_store.root,
            total,
            len(items),
        )
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

    def get_modeling_messages(self, project_id: str) -> dict:
        """读取当前项目建模活跃会话消息（项目空间 ``conversations/active.json``）。"""
        if not project_id or project_id == "undefined":
            return {"ok": False, "error": "Invalid project ID", "messages": []}
        try:
            msgs = self.project_store.load_messages(project_id)
            return {"ok": True, "messages": msgs}
        except Exception as e:
            _LOG.exception("[API] get_modeling_messages: %s", e)
            return {"ok": False, "error": str(e), "messages": []}

    def start_new_modeling_conversation(self, project_id: str) -> dict:
        """归档非空当前会话并清空活跃消息。"""
        if not project_id or project_id == "undefined":
            return {"ok": False, "error": "Invalid project ID"}
        try:
            sid = self.project_store.archive_active_conversation_and_clear(project_id)
            return {"ok": True, "archived_session_id": sid}
        except Exception as e:
            _LOG.exception("[API] start_new_modeling_conversation: %s", e)
            return {"ok": False, "error": str(e)}

    def list_modeling_conversation_history(self, project_id: str) -> dict:
        """列出建模历史会话摘要。"""
        if not project_id or project_id == "undefined":
            return {"ok": False, "error": "Invalid project ID", "items": []}
        try:
            items = self.project_store.list_modeling_conversation_history(project_id)
            return {"ok": True, "items": items}
        except Exception as e:
            _LOG.exception("[API] list_modeling_conversation_history: %s", e)
            return {"ok": False, "error": str(e), "items": []}

    def restore_modeling_conversation(self, project_id: str, session_id: str) -> dict:
        """从历史恢复为当前活跃会话。"""
        if not project_id or project_id == "undefined":
            return {"ok": False, "error": "Invalid project ID", "messages": []}
        if not session_id or not str(session_id).strip():
            return {"ok": False, "error": "Invalid session ID", "messages": []}
        try:
            msgs = self.project_store.restore_modeling_conversation(
                project_id, str(session_id).strip()
            )
            return {"ok": True, "messages": msgs}
        except FileNotFoundError as e:
            return {"ok": False, "error": str(e), "messages": []}
        except Exception as e:
            _LOG.exception("[API] restore_modeling_conversation: %s", e)
            return {"ok": False, "error": str(e), "messages": []}

    def _modeling_chat_core_body(
        self,
        project_id: str,
        user_message_raw: str,
        mode: str | None,
        on_llm_token: Callable[[str], None] | None = None,
    ) -> dict:
        """在已将本轮用户消息写入 store 后执行意图分类与 ReAct/Plan，并持久化助手回复。"""
        messages = self.project_store.load_messages(project_id)
        intent_scene = run_modeling_intent_scene_if_enabled(
            self.config, messages, user_message_raw
        )

        effective_mode = mode
        if effective_mode is None or not str(effective_mode).strip():
            effective_mode = self.config.agent.modeling_agent_mode or "react"

        prior = messages[:-1] if len(messages) > 1 else []
        task_for_agent = build_modeling_task_with_prior_dialogue(prior, user_message_raw)

        result = self.project_service.react_modeling(
            project_id=project_id,
            user_message=task_for_agent,
            card_manager=self.card_manager,
            web_search_func=self._get_web_search_func(),
            mode=str(effective_mode).strip().lower(),
            intent_scene=intent_scene if intent_scene else None,
            original_user_message=user_message_raw,
            on_llm_token=on_llm_token,
        )
        _LOG.info(
            "[API] modeling result: ok=%s, success=%s, mode_used=%s",
            result.get("ok"),
            result.get("success"),
            result.get("mode_used"),
        )

        if result.get("ok"):
            response_message = result.get("message") or "本轮建模会话已结束。"

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
                for step in result["steps"][-5:]:
                    th = (step.get("thought") or "").strip()
                    if th:
                        tcap = 120
                        steps_info += f"\n- 思考: {th[:tcap]}{'…' if len(th) > tcap else ''}"
                    act = (step.get("action") or "").strip()
                    if act and act != "FINAL_ANSWER":
                        steps_info += f"\n  行动: {act}"
                    if act == "ask_user":
                        inp = step.get("action_input") or {}
                        if isinstance(inp, dict):
                            q = (inp.get("question") or "").strip()
                            if q:
                                qcap = 280
                                qq = q if len(q) <= qcap else q[: qcap - 1] + "…"
                                steps_info += f"\n  问题: {qq}"
                            opts = inp.get("options")
                            if isinstance(opts, list) and opts:
                                steps_info += f"\n  （共 {len(opts)} 个选项）"
                    desc = (step.get("description") or "").strip()
                    if desc:
                        steps_info += f"\n- 步骤说明: {desc[:100]}{'…' if len(desc) > 100 else ''}"
                    obs = (step.get("observation") or "").strip()
                    if obs and (act == "plan_step" or (th.startswith("计划步骤:"))):
                        ocap = 140
                        oo = obs if len(obs) <= ocap else obs[: ocap - 1] + "…"
                        steps_info += f"\n  执行结果摘要: {oo}"
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
                "pending_ask_user_card": result.get("pending_ask_user_card"),
                "success": result.get("success", False),
                "modeling_substantive": bool(result.get("modeling_substantive", False)),
                "pending_user_input": result.get("pending_user_input", False),
                "tool_calls": result.get("tool_calls", 0),
                "mode_used": result.get("mode_used"),
                "mode_requested": result.get("mode_requested"),
                "plan": result.get("plan"),
                "replan_count": result.get("replan_count", 0),
            }
        error_msg = result.get("error", "建模失败")
        _LOG.warning("[API] modeling_chat failed: %s", error_msg)
        return {"ok": False, "message": error_msg}

    def modeling_chat(self, project_id: str, message: str, mode: str | None = None) -> dict:
        """
        建模对话（同步一次返回）。

        成功时返回字段含 ``message``、``steps``、``dst_state``、``success``、
        ``pending_user_input``（本轮 ReAct 图已结束；若末步为 ``ask_user`` 则等待用户
        下一条消息再开新轮，并非在同一次 ``invoke`` 内挂起）、
        ``pending_ask_user_card``（可选，追问 IM 卡片数据）、``mode_used`` 等。
        渐进式输出请用 ``start_modeling_chat_stream`` /
        ``poll_modeling_chat_stream``。
        ``mode`` 为 ``auto`` / ``react`` / ``plan``，省略时使用配置 ``modeling_agent_mode``。
        """
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

            return self._modeling_chat_core_body(project_id, message, mode, None)
        except Exception as e:
            _LOG.exception("[API] modeling_chat exception: %s", str(e))
            return {"ok": False, "message": str(e)}

    def start_modeling_chat_stream(
        self, project_id: str, message: str, mode: str | None = None
    ) -> dict:
        """
        启动后台建模会话并立即返回 ``stream_id``。
        前端轮询 ``poll_modeling_chat_stream`` 拉取 LLM token；``done`` 为真时
        ``result`` 与同步 ``modeling_chat`` 成功返回结构一致（含 ``pending_user_input``、
        ``pending_ask_user_card``）。
        """
        _LOG.info(
            "[API] start_modeling_chat_stream: project_id=%s, message_len=%d, mode=%s",
            project_id,
            len(message or ""),
            mode,
        )
        if not project_id or project_id == "undefined":
            return {"ok": False, "error": "Invalid project ID"}
        stream_id = str(uuid.uuid4())
        self._modeling_stream_hub.create(stream_id)

        try:
            messages = self.project_store.load_messages(project_id)
            messages.append(
                {
                    "role": "user",
                    "content": message,
                    "created_at": datetime.now().isoformat(),
                }
            )
            self.project_store.save_messages(project_id, messages)
        except Exception as e:
            self._modeling_stream_hub.fail(stream_id, str(e))
            return {"ok": False, "error": str(e), "stream_id": stream_id}

        hub = self._modeling_stream_hub
        api = self

        def worker() -> None:
            try:

                def cb(t: str) -> None:
                    hub.append_token(stream_id, t)

                out = api._modeling_chat_core_body(project_id, message, mode, cb)
                hub.finish(stream_id, out)
            except Exception as ex:
                _LOG.exception("[API] modeling stream worker: %s", ex)
                hub.fail(stream_id, str(ex))

        run_in_thread(worker, daemon=True)
        return {"ok": True, "stream_id": stream_id}

    def poll_modeling_chat_stream(self, stream_id: str) -> dict:
        """拉取自上次 poll 以来累积的 token；若 ``done``，同时返回 ``result`` 或 ``error``。"""
        if not stream_id or not str(stream_id).strip():
            return {"ok": False, "error": "Invalid stream_id", "tokens": [], "done": True}
        return self._modeling_stream_hub.poll(str(stream_id).strip())

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
