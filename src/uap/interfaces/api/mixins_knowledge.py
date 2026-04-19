"""项目知识库（Milvus Lite）API。"""

from __future__ import annotations

import json
from pathlib import Path

from uap.interfaces.api._log import _LOG


class KnowledgeApiMixin:
    def __init__(self):
        self.knowledge_service = None

    def _require_project(self, project_id: str) -> bool:
        try:
            self.project_store.get_project(project_id)
            return True
        except FileNotFoundError:
            return False

    def knowledge_base_status(self, project_id: str) -> dict:
        try:
            if not self._require_project(project_id):
                return {"ok": False, "error": "项目不存在"}
            out = self.knowledge_service.status(project_id)
            if isinstance(out, dict) and out.get("ok") is False and out.get("error"):
                _LOG.warning("[KB] status unavailable: %s", out.get("error")[:200])
            return out
        except Exception as e:
            _LOG.exception("[KB] status")
            return {"ok": False, "error": str(e)}

    def knowledge_base_ensure(self, project_id: str) -> dict:
        try:
            if not self._require_project(project_id):
                return {"ok": False, "error": "项目不存在"}
            return self.knowledge_service.ensure_collection(project_id)
        except Exception as e:
            _LOG.exception("[KB] ensure")
            return {"ok": False, "error": str(e)}

    def knowledge_base_import(self, project_id: str, file_path: str) -> dict:
        try:
            if not self._require_project(project_id):
                return {"ok": False, "error": "项目不存在"}
            return self.knowledge_service.import_file(project_id, file_path)
        except Exception as e:
            _LOG.exception("[KB] import")
            return {"ok": False, "error": str(e)}

    def knowledge_base_search(self, project_id: str, query: str, top_k: int = 5) -> dict:
        try:
            if not self._require_project(project_id):
                return {"ok": False, "error": "项目不存在"}
            return self.knowledge_service.search(project_id, query, top_k=top_k)
        except Exception as e:
            _LOG.exception("[KB] search")
            return {"ok": False, "error": str(e)}

    def knowledge_base_pick_file(self) -> dict:
        """打开系统文件选择对话框，返回本地路径（供导入知识库）。"""
        try:
            import webview

            windows = getattr(webview, "windows", None)
            if not windows:
                return {"success": False, "error": "窗口未就绪"}
            w = windows[0]
            result = w.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=(
                    "Markdown 与文本 (*.md;*.txt;*.markdown)",
                    "所有文件 (*.*)",
                ),
            )
            if not result:
                return {"success": False, "cancelled": True}
            path = result[0] if isinstance(result, (list, tuple)) else result
            return {"success": True, "path": path}
        except Exception as e:
            _LOG.exception("[KB] pick_file")
            return {"success": False, "error": str(e)}

    def get_memory_status(self, project_id: str) -> dict:
        """合并知识库状态、Episode 统计与最近一次定时辅助任务日志（供 UI）。"""
        try:
            if not self._require_project(project_id):
                return {"ok": False, "error": "项目不存在"}
            kb = self.knowledge_base_status(project_id)
            am_stats: dict = {"ok": False, "enabled": False}
            if getattr(self, "agent_memory", None) is not None:
                am_stats = self.agent_memory.stats(project_id)
            log_path = Path(self.project_store.root) / project_id / "auxiliary_schedule_log.json"
            aux: dict | None = None
            if log_path.is_file():
                try:
                    aux = json.loads(log_path.read_text(encoding="utf-8"))
                except Exception:
                    aux = None
            return {
                "ok": True,
                "knowledge": kb,
                "agent_memory": am_stats,
                "auxiliary_schedule_log": aux,
            }
        except Exception as e:
            _LOG.exception("[Memory] status")
            return {"ok": False, "error": str(e)}

    def run_memory_extraction(self, project_id: str) -> dict:
        """将未处理 Episode 写入项目向量库（与文档共用 collection）。"""
        try:
            if not self._require_project(project_id):
                return {"ok": False, "error": "项目不存在"}
            svc = getattr(self, "memory_extraction_service", None)
            if svc is None:
                return {"ok": False, "error": "memory_extraction_unavailable"}
            return svc.process_unprocessed(project_id)
        except Exception as e:
            _LOG.exception("[Memory] extraction")
            return {"ok": False, "error": str(e)}
