"""
UAP 预测执行服务

负责执行复杂系统的预测任务
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from src.uap.config import UapConfig
from src.uap.project.models import (
    PredictionConfig,
    PredictionResult,
    PredictionTask,
    Project,
    ProjectStatus,
)
from src.uap.project.project_store import ProjectStore

_LOG = logging.getLogger("uap.prediction_service")


class PredictionService:
    """预测执行服务"""
    
    def __init__(self, store: ProjectStore, cfg: UapConfig) -> None:
        self._store = store
        self._cfg = cfg
        self._running_predictions: dict[str, PredictionResult] = {}
    
    @property
    def store(self) -> ProjectStore:
        return self._store
    
    def run_prediction(
        self,
        project: Project,
        config: Optional[PredictionConfig] = None,
    ) -> PredictionResult:
        """
        执行预测任务
        
        这是一个简化实现，实际应该：
        1. 从数据源获取最新数据
        2. 调用 Koopman/PESM/PINN 等动力学模型
        3. 生成预测轨迹和置信区间
        4. 进行异常检测
        """
        if config is None:
            config = project.prediction_config
        
        result = PredictionResult(
            project_id=project.id,
            task_id="manual",
            prediction_time_start=datetime.now(timezone.utc).isoformat(),
            prediction_time_end=(
                datetime.now(timezone.utc) + timedelta(seconds=config.horizon_sec)
            ).isoformat(),
            confidence_level=config.confidence_level,
            method_used=config.method or "auto",
            horizon_achieved=config.horizon_sec,
        )
        
        start_time = time.perf_counter()
        project.set_predicting()
        self._store.update_project(project)
        
        try:
            _LOG.info("开始预测: project=%s, horizon=%ds", project.id, config.horizon_sec)
            
            # 检查是否有系统模型
            if project.system_model is None:
                result.status = "failed"
                result.error_message = "项目未定义系统模型"
                _LOG.warning("项目 %s 缺少系统模型", project.id)
                return result
            
            # TODO: 实际执行预测
            # 这里模拟一个简单的预测过程
            result = self._simulate_prediction(project, config, result)
            
            # 计算执行时间
            result.execution_time_ms = int((time.perf_counter() - start_time) * 1000)
            result.status = "completed"
            
            # 保存结果
            self._store.save_prediction_result(project.id, result)
            
            # 更新项目状态
            project.update_prediction_status(success=True)
            project.set_idle()
            self._store.update_project(project)
            
            _LOG.info(
                "预测完成: project=%s, result_id=%s, status=%s, time_ms=%d",
                project.id, result.id, result.status, result.execution_time_ms
            )
            
            return result
            
        except Exception as e:
            result.status = "failed"
            result.error_message = str(e)
            result.execution_time_ms = int((time.perf_counter() - start_time) * 1000)
            
            project.update_prediction_status(success=False)
            project.set_error(str(e))
            self._store.update_project(project)
            
            _LOG.exception("预测失败: project=%s", project.id)
            
            return result
    
    def _simulate_prediction(
        self,
        project: Project,
        config: PredictionConfig,
        result: PredictionResult,
    ) -> PredictionResult:
        """
        模拟预测过程
        
        TODO: 替换为真实的动力学模型预测
        """
        import random
        
        model = project.system_model
        horizon = config.horizon_sec
        horizon_hours = horizon / 3600
        
        # 生成模拟轨迹数据
        trajectory = []
        confidence_lower = []
        confidence_upper = []
        
        # 基于变量数量生成轨迹
        n_vars = len(model.variables) if model.variables else 3
        base_values = [random.uniform(0.5, 1.5) for _ in range(n_vars)]
        
        # 模拟预测点（每小时一个点）
        num_points = min(int(horizon_hours), 72)  # 最多72个点
        if num_points < 1:
            num_points = 1
        
        for i in range(num_points + 1):
            t = i / num_points  # 0 到 1 的相对时间
            
            point = {
                "time": (datetime.now(timezone.utc) + timedelta(hours=t * horizon_hours)).isoformat(),
                "relative_time": t,
            }
            
            # 为每个变量生成值
            for j, var in enumerate(model.variables) if model.variables else enumerate(["var1", "var2", "var3"]):
                var_name = var.name if isinstance(var, type(project.system_model.variables[0])) else str(var)
                # 模拟值变化：基础值 + 一些波动
                value = base_values[j] * (1 + 0.1 * t * (-1) ** i + 0.02 * random.gauss(0, 1))
                point[var_name] = round(value, 4)
            
            trajectory.append(point)
            
            # 置信区间随时间扩大
            uncertainty = 0.05 + 0.15 * t
            center = sum(point.get(v.name if hasattr(v, 'name') else str(v), 1.0) 
                        for v in (model.variables or [])) / max(len(model.variables), 1)
            confidence_lower.append(center - uncertainty)
            confidence_upper.append(center + uncertainty)
        
        result.trajectory = trajectory
        result.confidence_lower = [round(v, 4) for v in confidence_lower]
        result.confidence_upper = [round(v, 4) for v in confidence_upper]
        result.data_points_used = num_points * n_vars
        result.horizon_achieved = int(horizon_hours * 3600)
        
        # 计算关键指标
        if model.variables:
            result.key_metrics = {
                var.name: {
                    "mean": sum(t.get(var.name, 0) for t in trajectory) / len(trajectory),
                    "min": min(t.get(var.name, float('inf')) for t in trajectory),
                    "max": max(t.get(var.name, float('-inf')) for t in trajectory),
                    "final": trajectory[-1].get(var.name, 0) if trajectory else 0,
                }
                for var in model.variables
            }
        
        # 模拟异常检测
        # 随机决定是否有异常（实际应该基于模型）
        if random.random() < 0.1:  # 10% 概率检测到异常
            result.has_anomaly = True
            result.anomalies = [{
                "time": trajectory[-1]["time"],
                "variable": model.variables[0].name if model.variables else "unknown",
                "value": trajectory[-1].get(model.variables[0].name, 0) if model.variables else 0,
                "threshold": confidence_upper[-1] if confidence_upper else 1.5,
                "severity": "warning",
            }]
        
        # 系统状态评估
        if result.has_anomaly:
            result.system_state = "warning"
            result.turbulence_level = "transition"
        else:
            result.system_state = "normal"
            result.turbulence_level = "laminar"
        
        # 熵值（模拟）
        result.entropy_value = round(random.uniform(0.1, 0.5), 3)
        
        result.method_used = f"simulated_{config.method}"
        
        return result
    
    async def run_prediction_async(
        self,
        project: Project,
        config: Optional[PredictionConfig] = None,
    ) -> PredictionResult:
        """异步执行预测"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.run_prediction(project, config)
        )
    
    def get_prediction_result(
        self,
        project_id: str,
        result_id: str,
    ) -> dict:
        """获取预测结果"""
        result = self._store.load_prediction_result(project_id, result_id)
        if result is None:
            return {"ok": False, "error": "预测结果不存在"}
        return {"ok": True, "result": result.model_dump()}
    
    def list_prediction_results(
        self,
        project_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """列出预测结果"""
        results = self._store.list_prediction_results(project_id, limit, offset)
        return [r.to_summary() for r in results]
    
    def delete_prediction_result(
        self,
        project_id: str,
        result_id: str,
    ) -> dict:
        """删除预测结果"""
        try:
            self._store.delete_prediction_result(project_id, result_id)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    # ============ 预测任务调度 ============
    
    def create_prediction_task(
        self,
        project_id: str,
        trigger_type: str = "interval",
        interval_sec: int = 3600,
        daily_time: Optional[str] = None,
        label: str = "自动预测",
    ) -> dict:
        """创建预测任务"""
        try:
            project = self._store.get_project(project_id)
            
            tasks = self._store.load_tasks(project_id)
            
            # 创建新任务
            task = PredictionTask(
                project_id=project_id,
                trigger_type=trigger_type,
                interval_sec=interval_sec,
                daily_time=daily_time,
                label=label,
                enabled=True,
            )
            
            # 计算下次运行时间
            task.next_run_at = self._calculate_next_run(task)
            
            tasks.append(task)
            self._store.save_tasks(project_id, tasks)
            
            _LOG.info("创建预测任务: project=%s, task_id=%s", project_id, task.id)
            
            return {"ok": True, "task": task.model_dump()}
            
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
    
    def _calculate_next_run(self, task: PredictionTask) -> str:
        """计算任务下次运行时间"""
        now = datetime.now(timezone.utc)
        
        if task.trigger_type == "interval" and task.interval_sec:
            next_run = now + timedelta(seconds=task.interval_sec)
        elif task.trigger_type == "daily" and task.daily_time:
            # 解析 HH:MM 格式
            parts = task.daily_time.split(":")
            if len(parts) == 2:
                hour, minute = int(parts[0]), int(parts[1])
                next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(days=1)
            else:
                next_run = now + timedelta(hours=1)
        elif task.trigger_type == "startup":
            next_run = now
        else:
            next_run = now + timedelta(hours=1)
        
        return next_run.isoformat()
    
    def get_prediction_tasks(self, project_id: str) -> list[dict]:
        """获取项目的预测任务"""
        tasks = self._store.load_tasks(project_id)
        return [t.model_dump() for t in tasks]
    
    def delete_prediction_task(self, project_id: str, task_id: str) -> dict:
        """删除预测任务"""
        try:
            tasks = self._store.load_tasks(project_id)
            tasks = [t for t in tasks if t.id != task_id]
            self._store.save_tasks(project_id, tasks)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def process_due_tasks(self) -> dict:
        """
        处理到期的预测任务
        
        由调度器调用
        """
        processed = 0
        errors = []
        
        for project in self._store.list_projects():
            if not project.prediction_config.enabled:
                continue
            
            tasks = self._store.load_tasks(project.id)
            now = datetime.now(timezone.utc)
            
            for task in tasks:
                if not task.enabled:
                    continue
                
                if task.next_run_at is None:
                    continue
                
                # 检查是否到期
                next_run = datetime.fromisoformat(task.next_run_at.replace("Z", "+00:00"))
                if next_run > now:
                    continue
                
                # 执行预测
                try:
                    result = self.run_prediction(project)
                    
                    task.last_run_at = datetime.now(timezone.utc).isoformat()
                    task.last_run_status = "success" if result.status == "completed" else "failed"
                    task.last_error = result.error_message
                    task.run_count += 1
                    if result.status == "completed":
                        task.success_count += 1
                    
                    processed += 1
                    
                except Exception as e:
                    task.last_run_at = datetime.now(timezone.utc).isoformat()
                    task.last_run_status = "failed"
                    task.last_error = str(e)
                    errors.append(f"project={project.id}: {str(e)}")
                
                # 更新下次运行时间
                task.next_run_at = self._calculate_next_run(task)
            
            self._store.save_tasks(project.id, tasks)
        
        return {
            "processed": processed,
            "errors": errors,
        }
