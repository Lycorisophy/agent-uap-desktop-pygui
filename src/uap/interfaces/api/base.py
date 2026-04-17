"""UAPApi 构造与调度器生命周期。"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

from uap.card.models import CardResponse, CardType
from uap.config import load_config, UAPConfig
from uap.infrastructure.persistence.project_store import ProjectStore
from uap.application.project_service import ProjectService
from uap.application.prediction_service import PredictionService
from uap.scheduler import TaskScheduler, SchedulerConfig
from uap.card import CardManager, CardGenerator
from uap.skill import get_atomic_skills_library
from uap.infrastructure.knowledge import ProjectKnowledgeService
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

        self.card_manager = CardManager(default_timeout=300)
        self.card_generator = CardGenerator()

        self.atomic_skills = get_atomic_skills_library()
        self.knowledge_service = ProjectKnowledgeService(self.config)
        self._modeling_stream_hub = ModelingStreamHub()

        self.card_manager.register_callback(
            CardType.ASK_USER, self._on_ask_user_card_response
        )
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

    def _on_prediction_task(self, project_id: str):
        try:
            project = self.project_store.get_project(project_id)
            if not project:
                print(f"Project not found: {project_id}")
                return

            result = self.prediction_service.run_prediction(
                project,
                project.prediction_config,
            )

            self.project_store.save_prediction_result(project_id, result)

            project.last_prediction_at = result.created_at
            self.project_store.save_project(project)

        except Exception as e:
            print(f"Prediction task failed: {e}")
