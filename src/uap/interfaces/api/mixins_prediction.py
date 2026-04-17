"""预测任务、结果与调度器控制 API。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from uap.interfaces.api._log import _LOG
from uap.infrastructure.scheduler.task_scheduler import TaskStatus
from uap.project.models import PredictionConfig


class PredictionApiMixin:
    def save_prediction_config(self, project_id: str, config_data: dict) -> dict:
        """Save prediction config"""
        cfg = PredictionConfig.model_validate(config_data)
        return self.project_service.save_prediction_config(project_id, cfg)

    def update_prediction_config(
        self,
        project_id: str,
        frequency_sec: int,
        horizon_sec: int,
    ) -> dict:
        """Update prediction frequency and horizon from the desktop UI."""
        project = self.project_store.get_project(project_id)
        if not project:
            return {"success": False, "error": "Project not found"}
        cfg = project.prediction_config.model_copy(
            update={
                "frequency_sec": int(frequency_sec),
                "horizon_sec": int(horizon_sec),
            }
        )
        out = self.project_service.save_prediction_config(project_id, cfg)
        if out.get("ok"):
            return {"success": True}
        return {"success": False, "error": out.get("error", "Save failed")}

    def start_prediction(self, project_id: str) -> dict:
        """Start periodic prediction: register interval task and run scheduler."""
        project = self.project_store.get_project(project_id)
        if not project:
            return {"success": False, "error": "Project not found"}
        interval_sec = project.prediction_config.frequency_sec
        r = self.create_prediction_task(project_id, "interval", interval_sec)
        if r.get("success"):
            self.scheduler.start()
            return {"success": True, "task_id": r.get("task_id")}
        if r.get("task_id"):
            self.scheduler.start()
            return {"success": True, "task_id": r["task_id"], "already_running": True}
        return r

    def stop_prediction(self, project_id: str) -> dict:
        """Remove all scheduled tasks for the project (stops periodic prediction)."""
        tasks = self.scheduler.get_project_tasks(project_id)
        removed = 0
        for t in tasks:
            if self.scheduler.remove_task(t.id):
                removed += 1
        return {"success": True, "removed": removed}

    def get_prediction_config(self, project_id: str) -> Optional[dict]:
        """Get prediction config"""
        project = self.project_store.get_project(project_id)
        if project:
            return project.prediction_config.model_dump()
        return None

    def create_prediction_task(
        self,
        project_id: str,
        trigger_type: str = "interval",
        interval_seconds: int = 3600,
    ) -> dict:
        """Create prediction task"""
        project = self.project_store.get_project(project_id)
        if not project:
            return {"success": False, "error": "Project not found"}

        existing_tasks = self.scheduler.get_project_tasks(project_id)
        active_tasks = [
            t
            for t in existing_tasks
            if t.status in (TaskStatus.PENDING.value, TaskStatus.RUNNING.value)
        ]
        if active_tasks:
            return {
                "success": False,
                "error": "Active prediction task already exists",
                "task_id": active_tasks[0].id,
            }

        if trigger_type == "interval":
            task = self.scheduler.add_interval_task(project_id, interval_seconds)
        elif trigger_type == "cron":
            task = self.scheduler.add_cron_task(project_id, "0 * * * *")
        else:
            task = self.scheduler.add_one_time_task(project_id, datetime.now())

        return {
            "success": True,
            "task_id": task.id,
            "task": task.model_dump(),
        }

    def get_prediction_task(self, task_id: str) -> Optional[dict]:
        """Get task info"""
        task = self.scheduler.get_task(task_id)
        return task.model_dump() if task else None

    def get_project_tasks(self, project_id: str) -> list[dict]:
        """Get all tasks for project"""
        tasks = self.scheduler.get_project_tasks(project_id)
        return [t.model_dump() for t in tasks]

    def pause_prediction_task(self, task_id: str) -> dict:
        """Pause prediction task"""
        success = self.scheduler.pause_task(task_id)
        return {"success": success, "task_id": task_id}

    def resume_prediction_task(self, task_id: str) -> dict:
        """Resume prediction task"""
        success = self.scheduler.resume_task(task_id)
        return {"success": success, "task_id": task_id}

    def delete_prediction_task(self, task_id: str) -> dict:
        """Delete prediction task"""
        success = self.scheduler.remove_task(task_id)
        return {"success": success, "task_id": task_id}

    def run_prediction_now(self, project_id: str) -> dict:
        """Run prediction immediately"""
        _LOG.info("[API] run_prediction_now called: project_id=%s", project_id)
        project = self.project_store.get_project(project_id)
        if not project:
            _LOG.warning("[API] run_prediction_now: project not found: %s", project_id)
            return {"success": False, "error": "Project not found"}

        _LOG.info("[API] Starting prediction with config: %s", project.prediction_config)
        result = self.prediction_service.run_prediction(
            project,
            project.prediction_config,
        )
        _LOG.info(
            "[API] Prediction completed: status=%s, result_id=%s",
            result.status,
            result.id,
        )

        self.project_store.save_prediction_result(project_id, result)
        project.last_prediction_at = result.created_at
        self.project_store.save_project(project)

        return {
            "success": True,
            "result": result.model_dump(),
        }

    def get_prediction_results(
        self,
        project_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        """Get prediction result list"""
        results = self.project_store.list_prediction_results(project_id, limit, offset)
        return {
            "items": [r.model_dump() for r in results],
            "total": len(results),
        }

    def get_prediction_result(self, project_id: str, result_id: str) -> Optional[dict]:
        """Get single prediction result"""
        result = self.project_store.get_prediction_result(project_id, result_id)
        return result.model_dump() if result else None

    def get_scheduler_status(self) -> dict:
        """Get scheduler status"""
        return self.scheduler.get_status()

    def start_scheduler(self) -> dict:
        """Start scheduler"""
        self.scheduler.start()
        return {"success": True, "running": True}

    def stop_scheduler(self) -> dict:
        """Stop scheduler"""
        self.scheduler.stop()
        return {"success": True, "running": False}
