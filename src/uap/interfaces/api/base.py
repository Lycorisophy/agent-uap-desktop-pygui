"""UAPApi 构造与调度器生命周期。"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from uap.application.memory_extraction_service import MemoryExtractionService
from uap.core.memory.agent_memory_persistence import AgentMemoryPersistence, agent_memory_db_path

from uap.card.models import CardResponse, CardType
from uap.config import load_config, UAPConfig
from uap.infrastructure.persistence.project_store import ProjectStore
from uap.application.project_service import ProjectService
from uap.application.prediction_service import PredictionService
from uap.scheduler import TaskScheduler, SchedulerConfig
from uap.card import CardManager, CardGenerator
from uap.card.persistence import CardPersistence
from uap.skill import get_atomic_skills_library
from uap.infrastructure.knowledge import create_project_knowledge_service
from uap.infrastructure.modeling_stream_hub import ModelingStreamHub

_LOG = logging.getLogger("uap.api.base")


class UAPApiBase:
    """初始化共享依赖与后台调度。"""

    def __init__(self, config: Optional[UAPConfig] = None):
        self.config = config or load_config()
        raw_root = self.config.storage.projects_root or os.path.join(
            os.path.expanduser("~"), ".uap", "projects"
        )
        projects_root = str(Path(raw_root).expanduser().resolve())
        self.project_store = ProjectStore(projects_root, uap_cfg=self.config)
        self.project_service = ProjectService(self.project_store, self.config)
        self.prediction_service = PredictionService(self.project_store, self.config)
        self.scheduler = self._init_scheduler()

        _idx = Path(projects_root) / "_uap_index"
        _idx.mkdir(parents=True, exist_ok=True)
        self.card_persistence = CardPersistence(_idx / "cards.sqlite")
        self.card_manager = CardManager(default_timeout=300, persistence=self.card_persistence)
        self.card_generator = CardGenerator()

        self.atomic_skills = get_atomic_skills_library()
        self.knowledge_service = create_project_knowledge_service(self.config)
        self.agent_memory = AgentMemoryPersistence(agent_memory_db_path(projects_root))
        self.memory_extraction_service = MemoryExtractionService(
            self.agent_memory, self.knowledge_service
        )
        self._modeling_stream_hub = ModelingStreamHub()

        self.card_manager.register_callback(
            CardType.ASK_USER, self._on_ask_user_card_response
        )
        self.project_service.attach_card_manager(self.card_manager)
        self._spawn_card_expiry_watcher()

    def _on_ask_user_card_response(self, response: CardResponse) -> None:
        """追问卡超时/拒绝/关闭：仅追加会话，不调用建模 LLM。"""
        sel = response.selected_option_id
        meta = response.metadata or {}
        reason = str(meta.get("reason") or "")
        if (
            sel not in ("__timeout__", "__reject__", "dismissed")
            and reason != "timeout"
        ):
            return
        pid = str(meta.get("project_id") or "").strip()
        if not pid:
            _LOG.warning("ASK_USER card response without project_id")
            return
        if sel == "__timeout__" or reason == "timeout":
            line = "（系统）追问卡片已超时，未将本次选择发给模型。"
        elif sel == "__reject__":
            line = "（系统）用户已跳过本次追问，未将本次选择发给模型。"
        else:
            line = "（系统）追问卡片已关闭，未将本次选择发给模型。"
        from datetime import datetime

        msgs = self.project_store.load_messages(pid)
        msgs.append(
            {
                "role": "assistant",
                "content": line,
                "created_at": datetime.now().isoformat(),
            }
        )
        self.project_store.save_messages(pid, msgs)

    def _spawn_card_expiry_watcher(self) -> None:
        """周期性触发过期清理（追问卡超时依赖此线程或 API 轮询）。"""

        def loop() -> None:
            while True:
                time.sleep(15)
                try:
                    self.card_manager.get_pending_cards()
                except Exception:
                    _LOG.exception("card_expiry_watcher")

        threading.Thread(target=loop, daemon=True, name="uap_card_expiry").start()

    def _init_scheduler(self) -> TaskScheduler:
        scheduler_config = SchedulerConfig(
            check_interval=self.config.scheduler.tick_interval_sec,
            max_concurrent_tasks=self.config.scheduler.max_projects_per_tick,
            task_timeout=300,
            retry_times=3,
            retry_interval=60,
            enabled=self.config.scheduler.enabled,
        )

        scheduler = TaskScheduler(scheduler_config)
        scheduler.set_tasks_file(
            os.path.join(self.project_store.root, "scheduled_tasks.json")
        )
        scheduler.set_task_callback(self._on_prediction_task)
        scheduler.load_tasks()

        return scheduler

    def _write_auxiliary_schedule_log(self, project_id: str, flow: dict[str, Any]) -> None:
        """供前端展示最近一次定时辅助任务分支与意图（落盘于项目目录）。"""
        try:
            p = Path(self.project_store.root) / project_id / "auxiliary_schedule_log.json"
            payload = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "branch": flow.get("branch"),
                "scheduled_next": flow.get("scheduled_next"),
                "intent_scene": flow.get("intent_scene"),
                "ok": bool(flow.get("ok")),
            }
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            _LOG.debug("auxiliary_schedule_log: %s", e)

    def _on_prediction_task(self, project_id: str):
        try:
            project = self.project_store.get_project(project_id)
            if not project:
                print(f"Project not found: {project_id}")
                return

            trigger_line = (
                f"[定时任务触发] 项目「{project.name or project_id}」按计划执行辅助检查；"
                "无用户在线，请结合项目模型与配置选择后续动作（预测 / ReAct / Plan / 跳过）。"
            )
            flow = self.project_service.run_scheduled_auxiliary_flow(
                project_id,
                trigger_line,
                self.prediction_service,
            )

            if not flow.get("ok"):
                _LOG.warning(
                    "Scheduled task flow failed project=%s err=%s",
                    project_id,
                    flow.get("error"),
                )
                return

            self._write_auxiliary_schedule_log(project_id, flow)

            branch = str(flow.get("branch") or "").strip().lower()
            if branch == "none":
                _LOG.info(
                    "Scheduled task skipped (none) project=%s intent=%s",
                    project_id,
                    (flow.get("intent_scene") or {}).get("classified_intent"),
                )
                return

            if branch == "prediction":
                pred_res = flow.get("prediction_result")
                if pred_res is None:
                    _LOG.warning("Scheduled prediction branch missing result project=%s", project_id)
                    return
                self.project_store.save_prediction_result(project_id, pred_res)
                project = self.project_store.get_project(project_id) or project
                project.last_prediction_at = pred_res.created_at
                self.project_store.save_project(project)
                return

            msg = (flow.get("message") or "").strip()
            if msg:
                msgs = self.project_store.load_messages(project_id)
                msgs.append(
                    {
                        "role": "assistant",
                        "content": f"（定时任务·{branch}）\n{msg}",
                        "created_at": datetime.now().isoformat(),
                    }
                )
                self.project_store.save_messages(project_id, msgs)

        except Exception as e:
            _LOG.exception("Prediction task failed: %s", e)
            print(f"Prediction task failed: {e}")
