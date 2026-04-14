"""
UAP API 类
提供JavaScript前端调用的Python API
"""

import json
import os
from typing import Optional, Any

from uap.config import load_config, UAPConfig
from uap.project.models import (
    Project, ProjectStatus, SystemModel, PredictionConfig,
    PredictionTask, PredictionResult, ModelSource
)
from uap.project.project_store import ProjectStore
from uap.service.project_service import ProjectService
from uap.service.prediction_service import PredictionService
from uap.scheduler import TaskScheduler, SchedulerConfig


class UAPApi:
    """
    UAP 对外API接口
    提供给前端JavaScript调用的接口封装
    """

    def __init__(self, config: Optional[UAPConfig] = None):
        self.config = config or load_config()
        self.project_store = ProjectStore(self.config.projects_dir)
        self.project_service = ProjectService(self.project_store)
        self.prediction_service = PredictionService(self.project_store)
        self.scheduler = self._init_scheduler()

    def _init_scheduler(self) -> TaskScheduler:
        """初始化调度器"""
        scheduler_config = SchedulerConfig(
            check_interval=self.config.scheduler.check_interval,
            max_concurrent_tasks=self.config.scheduler.max_concurrent_tasks,
            task_timeout=self.config.scheduler.task_timeout,
            retry_times=self.config.scheduler.retry_times,
            retry_interval=self.config.scheduler.retry_interval,
            enabled=self.config.scheduler.enabled
        )

        scheduler = TaskScheduler(scheduler_config)
        scheduler.set_tasks_file(
            os.path.join(self.config.projects_dir, 'scheduled_tasks.json')
        )
        scheduler.set_task_callback(self._on_prediction_task)
        scheduler.load_tasks()

        return scheduler

    def _on_prediction_task(self, project_id: str):
        """预测任务回调"""
        try:
            project = self.project_store.get_project(project_id)
            if not project:
                print(f"Project not found: {project_id}")
                return

            result = self.prediction_service.run_prediction(
                project,
                project.prediction_config
            )

            # 保存预测结果
            self.project_store.save_prediction_result(project_id, result)

            # 更新项目状态
            project.last_prediction_at = result.predicted_at
            self.project_store.save_project(project)

        except Exception as e:
            print(f"Prediction task failed: {e}")

    # ==================== 项目管理 API ====================

    def create_project(self, name: str, description: str = "") -> dict:
        """
        创建新项目

        Args:
            name: 项目名称
            description: 项目描述

        Returns:
            项目信息字典
        """
        return self.project_service.create_project(name, description)

    def get_project(self, project_id: str) -> Optional[dict]:
        """获取项目信息"""
        project = self.project_store.get_project(project_id)
        return project.model_dump() if project else None

    def list_projects(self, limit: int = 50, offset: int = 0) -> dict:
        """列出所有项目"""
        projects = self.project_store.list_projects(limit, offset)
        return {
            "items": [p.model_dump() for p in projects],
            "total": len(projects)
        }

    def delete_project(self, project_id: str) -> dict:
        """删除项目"""
        # 停止相关任务
        tasks = self.scheduler.get_project_tasks(project_id)
        for task in tasks:
            self.scheduler.remove_task(task.id)

        # 删除项目
        self.project_store.delete_project(project_id)
        return {"success": True, "project_id": project_id}

    # ==================== 系统模型 API ====================

    def save_model(self, project_id: str, model_data: dict) -> dict:
        """
        保存系统模型

        Args:
            project_id: 项目ID
            model_data: 模型数据（变量、关系、约束等）

        Returns:
            保存结果
        """
        model = SystemModel(**model_data)
        self.project_store.save_model(project_id, model)

        # 更新项目状态
        project = self.project_store.get_project(project_id)
        if project:
            project.status = ProjectStatus.MODELING
            self.project_store.save_project(project)

        return {"success": True, "project_id": project_id}

    def get_model(self, project_id: str) -> Optional[dict]:
        """获取系统模型"""
        project = self.project_store.get_project(project_id)
        if project and project.system_model:
            return project.system_model.model_dump()
        return None

    def extract_model_from_conversation(
        self,
        project_id: str,
        messages: list[dict],
        user_prompt: str
    ) -> dict:
        """
        从对话中提取系统模型

        Args:
            project_id: 项目ID
            messages: 对话历史消息
            user_prompt: 用户的提示词

        Returns:
            提取的模型数据
        """
        return self.project_service.extract_model_from_conversation(
            project_id, messages, user_prompt
        )

    def import_model_from_document(
        self,
        project_id: str,
        document_content: str,
        document_name: str
    ) -> dict:
        """
        从文档导入系统模型

        Args:
            project_id: 项目ID
            document_content: 文档内容
            document_name: 文档名称

        Returns:
            导入结果
        """
        return self.project_service.import_model_from_document(
            project_id, document_content, document_name
        )

    # ==================== 预测配置 API ====================

    def save_prediction_config(
        self,
        project_id: str,
        config_data: dict
    ) -> dict:
        """
        保存预测配置

        Args:
            project_id: 项目ID
            config_data: 配置数据（频率、预测时长等）

        Returns:
            保存结果
        """
        return self.project_service.save_prediction_config(project_id, config_data)

    def get_prediction_config(self, project_id: str) -> Optional[dict]:
        """获取预测配置"""
        project = self.project_store.get_project(project_id)
        if project:
            return project.prediction_config.model_dump()
        return None

    # ==================== 预测任务 API ====================

    def create_prediction_task(
        self,
        project_id: str,
        trigger_type: str = "interval",
        interval_seconds: int = 3600
    ) -> dict:
        """
        创建预测任务

        Args:
            project_id: 项目ID
            trigger_type: 触发类型（interval/cron/one_time）
            interval_seconds: 间隔秒数（interval类型时使用）

        Returns:
            任务信息
        """
        # 验证项目存在
        project = self.project_store.get_project(project_id)
        if not project:
            return {"success": False, "error": "Project not found"}

        # 检查是否已有活跃任务
        existing_tasks = self.scheduler.get_project_tasks(project_id)
        active_tasks = [t for t in existing_tasks if t.status.value in ['pending', 'running']]
        if active_tasks:
            return {
                "success": False,
                "error": "Active prediction task already exists",
                "task_id": active_tasks[0].id
            }

        # 创建任务
        if trigger_type == "interval":
            task = self.scheduler.add_interval_task(
                project_id, interval_seconds
            )
        elif trigger_type == "cron":
            task = self.scheduler.add_cron_task(
                project_id, "0 * * * *"  # 每小时
            )
        else:
            task = self.scheduler.add_one_time_task(
                project_id,
                datetime.now()
            )

        return {
            "success": True,
            "task_id": task.id,
            "task": task.model_dump()
        }

    def get_prediction_task(self, task_id: str) -> Optional[dict]:
        """获取任务信息"""
        task = self.scheduler.get_task(task_id)
        return task.model_dump() if task else None

    def get_project_tasks(self, project_id: str) -> list[dict]:
        """获取项目的所有任务"""
        tasks = self.scheduler.get_project_tasks(project_id)
        return [t.model_dump() for t in tasks]

    def pause_prediction_task(self, task_id: str) -> dict:
        """暂停预测任务"""
        success = self.scheduler.pause_task(task_id)
        return {"success": success, "task_id": task_id}

    def resume_prediction_task(self, task_id: str) -> dict:
        """恢复预测任务"""
        success = self.scheduler.resume_task(task_id)
        return {"success": success, "task_id": task_id}

    def delete_prediction_task(self, task_id: str) -> dict:
        """删除预测任务"""
        success = self.scheduler.remove_task(task_id)
        return {"success": success, "task_id": task_id}

    def run_prediction_now(self, project_id: str) -> dict:
        """
        立即执行预测（不等待调度器）

        Args:
            project_id: 项目ID

        Returns:
            预测结果
        """
        project = self.project_store.get_project(project_id)
        if not project:
            return {"success": False, "error": "Project not found"}

        result = self.prediction_service.run_prediction(
            project,
            project.prediction_config
        )

        self.project_store.save_prediction_result(project_id, result)

        project.last_prediction_at = result.predicted_at
        self.project_store.save_project(project)

        return {
            "success": True,
            "result": result.model_dump()
        }

    # ==================== 预测结果 API ====================

    def get_prediction_results(
        self,
        project_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> dict:
        """获取预测结果列表"""
        results = self.project_store.list_prediction_results(
            project_id, limit, offset
        )
        return {
            "items": [r.model_dump() for r in results],
            "total": len(results)
        }

    def get_prediction_result(self, project_id: str, result_id: str) -> Optional[dict]:
        """获取单个预测结果"""
        result = self.project_store.get_prediction_result(project_id, result_id)
        return result.model_dump() if result else None

    # ==================== 调度器状态 API ====================

    def get_scheduler_status(self) -> dict:
        """获取调度器状态"""
        return self.scheduler.get_status()

    def start_scheduler(self) -> dict:
        """启动调度器"""
        self.scheduler.start()
        return {"success": True, "running": True}

    def stop_scheduler(self) -> dict:
        """停止调度器"""
        self.scheduler.stop()
        return {"success": True, "running": False}

    # ==================== 配置 API ====================

    def get_config(self) -> dict:
        """获取当前配置"""
        return {
            "prediction_defaults": self.config.prediction_defaults.model_dump(),
            "llm": self.config.llm.model_dump(),
            "storage": self.config.storage.model_dump(),
        }

    def update_config(self, config_updates: dict) -> dict:
        """
        更新配置（仅内存中，不持久化）

        Args:
            config_updates: 要更新的配置项

        Returns:
            更新结果
        """
        # 这里可以实现配置热更新
        return {"success": True, "message": "Config updated"}


from datetime import datetime
