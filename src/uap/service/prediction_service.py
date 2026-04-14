"""
UAP 预测执行服务

负责执行复杂系统的预测任务
集成Koopman、Monte Carlo等预测引擎
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from uap.config import UapConfig
from uap.engine import (
    Predictor,
    PredictionMethod,
    create_predictor,
    MonteCarloPredictor,
    KoopmanPredictor,
    SystemSimulator
)
from uap.project.models import (
    PredictionConfig,
    PredictionResult,
    PredictionTask,
    Project,
)
from uap.project.project_store import ProjectStore

_LOG = logging.getLogger("uap.prediction_service")


class PredictionService:
    """
    预测执行服务
    
    负责执行复杂系统的预测任务，支持多种预测方法。
    """
    
    def __init__(self, store: ProjectStore, cfg: UapConfig) -> None:
        """
        初始化预测服务
        
        Args:
            store: 项目存储实例
            cfg: 应用配置
        """
        self._store = store
        self._cfg = cfg
        self._running_predictions: dict[str, PredictionResult] = {}
    
    @property
    def store(self) -> ProjectStore:
        """获取项目存储"""
        return self._store
    
    def run_prediction(
        self,
        project: Project,
        config: Optional[PredictionConfig] = None,
    ) -> PredictionResult:
        """
        执行预测任务
        
        使用选定的预测方法（Koopman/Monte Carlo/Simulation）对复杂系统进行预测。
        
        Args:
            project: 项目实体
            config: 预测配置，默认使用项目配置
            
        Returns:
            PredictionResult: 预测结果
        """
        if config is None:
            config = project.prediction_config
        
        start_time = time.perf_counter()
        
        # 创建结果对象
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
        
        project.set_predicting()
        self._store.update_project(project)
        
        try:
            _LOG.info(
                "开始预测: project=%s, method=%s, horizon=%ds",
                project.id, config.method, config.horizon_sec
            )
            
            # 检查是否有系统模型
            if project.system_model is None:
                result.status = "failed"
                result.error_message = "项目未定义系统模型"
                _LOG.warning("项目 %s 缺少系统模型", project.id)
                return result
            
            # 检查模型是否有效
            if not project.system_model.variables:
                result.status = "failed"
                result.error_message = "系统模型没有定义变量"
                _LOG.warning("项目 %s 的模型没有变量", project.id)
                return result
            
            # 创建预测器
            predictor = self._create_predictor(project, config)
            
            # 获取初始状态
            initial_state = self._get_initial_state(project)
            
            # 执行预测
            raw_result = predictor.predict(
                initial_state=initial_state,
                horizon_sec=config.horizon_sec,
                frequency_sec=config.frequency_sec or 3600,  # 默认每小时
            )
            
            # 转换结果格式
            result.trajectory = raw_result.trajectory
            result.confidence_lower = raw_result.confidence_lower
            result.confidence_upper = raw_result.confidence_upper
            result.anomalies = raw_result.anomalies
            result.system_state = raw_result.system_state
            result.entropy_value = raw_result.entropy_value
            result.turbulence_level = raw_result.turbulence_level
            result.method_used = raw_result.method
            
            # 计算关键指标
            result.key_metrics = self._calculate_metrics(result.trajectory, project)
            result.data_points_used = len(result.trajectory)
            
            # 设置状态
            result.status = "completed"
            
            # 计算执行时间
            result.execution_time_ms = int((time.perf_counter() - start_time) * 1000)
            
            # 保存结果
            self._store.save_prediction_result(project.id, result)
            
            # 更新项目状态
            project.update_prediction_status(success=True)
            project.set_idle()
            self._store.update_project(project)
            
            _LOG.info(
                "预测完成: project=%s, result_id=%s, method=%s, points=%d, time_ms=%d",
                project.id, result.id, result.method_used,
                len(result.trajectory), result.execution_time_ms
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
    
    def _create_predictor(
        self,
        project: Project,
        config: PredictionConfig
    ) -> Predictor:
        """
        创建预测器实例
        
        Args:
            project: 项目实体
            config: 预测配置
            
        Returns:
            Predictor: 预测器实例
        """
        model = project.system_model
        
        # 根据配置选择预测方法
        method = config.method or "monte_carlo"
        
        if method == "koopman":
            predictor = KoopmanPredictor(model)
            # 如果有历史预测数据，可以进行训练
            history = self._get_training_data(project)
            if history:
                predictor.fit(history, method="dmd")
        elif method == "simulation":
            predictor = SystemSimulator(model)
        else:
            # 默认使用Monte Carlo
            predictor = MonteCarloPredictor(model, n_simulations=100)
        
        return predictor
    
    def _get_initial_state(self, project: Project) -> dict[str, float]:
        """
        获取初始状态
        
        从项目数据或历史预测结果中获取系统变量的初始值。
        
        Args:
            project: 项目实体
            
        Returns:
            dict: 变量名到初始值的映射
        """
        initial_state = {}
        
        # 1. 尝试从模型变量定义中获取默认值
        if project.system_model and project.system_model.variables:
            for var in project.system_model.variables:
                # 如果变量有范围，取中间值作为初始值
                if var.range:
                    min_val = var.range.get("min", 0)
                    max_val = var.range.get("max", 100)
                    initial_state[var.name] = (min_val + max_val) / 2
                else:
                    initial_state[var.name] = 1.0  # 默认值
        
        # 2. 尝试从最新预测结果获取
        if not initial_state or all(v == 1.0 for v in initial_state.values()):
            latest_result = self._get_latest_result(project.id)
            if latest_result and latest_result.trajectory:
                last_point = latest_result.trajectory[-1]
                if "values" in last_point:
                    initial_state = last_point["values"]
        
        return initial_state
    
    def _get_training_data(self, project: Project) -> Optional[list]:
        """
        获取训练数据用于Koopman算子学习
        
        Args:
            project: 项目实体
            
        Returns:
            list: 历史轨迹数据
        """
        # 获取最近几次预测结果
        results = self._store.list_prediction_results(project.id, limit=10)
        
        if not results:
            return None
        
        trajectories = []
        for result in results:
            if result.trajectory:
                trajectories.append({"states": result.trajectory})
        
        return trajectories if trajectories else None
    
    def _get_latest_result(self, project_id: str) -> Optional[PredictionResult]:
        """获取最新的预测结果"""
        results = self._store.list_prediction_results(project_id, limit=1)
        return results[0] if results else None
    
    def _calculate_metrics(
        self,
        trajectory: list[dict],
        project: Project
    ) -> dict:
        """
        计算关键指标
        
        Args:
            trajectory: 预测轨迹
            project: 项目实体
            
        Returns:
            dict: 关键指标
        """
        if not trajectory:
            return {}
        
        metrics = {}
        
        for var in (project.system_model.variables or []):
            values = []
            for point in trajectory:
                # 支持两种格式
                if "values" in point:
                    values.append(point["values"].get(var.name, 0))
                else:
                    values.append(point.get(var.name, 0))
            
            if values:
                import numpy as np
                metrics[var.name] = {
                    "mean": round(float(np.mean(values)), 4),
                    "min": round(float(np.min(values)), 4),
                    "max": round(float(np.max(values)), 4),
                    "std": round(float(np.std(values)), 4),
                    "final": round(values[-1], 4),
                }
        
        return metrics
    
    def get_prediction_result(
        self,
        project_id: str,
        result_id: str,
    ) -> dict:
        """
        获取预测结果
        
        Args:
            project_id: 项目ID
            result_id: 结果ID
            
        Returns:
            dict: 预测结果
        """
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
        """
        列出预测结果
        
        Args:
            project_id: 项目ID
            limit: 返回数量限制
            offset: 偏移量
            
        Returns:
            list[dict]: 预测结果列表
        """
        results = self._store.list_prediction_results(project_id, limit, offset)
        return [r.to_summary() for r in results]
    
    def delete_prediction_result(
        self,
        project_id: str,
        result_id: str,
    ) -> dict:
        """
        删除预测结果
        
        Args:
            project_id: 项目ID
            result_id: 结果ID
            
        Returns:
            dict: 删除结果
        """
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
        """
        创建预测任务
        
        Args:
            project_id: 项目ID
            trigger_type: 触发类型
            interval_sec: 间隔秒数
            daily_time: 每日时间（HH:MM格式）
            label: 任务标签
            
        Returns:
            dict: 创建结果
        """
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
            
            _LOG.info(
                "创建预测任务: project=%s, task_id=%s, trigger=%s, interval=%ds",
                project_id, task.id, trigger_type, interval_sec
            )
            
            return {"ok": True, "task": task.model_dump()}
            
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
    
    def _calculate_next_run(self, task: PredictionTask) -> str:
        """
        计算任务下次运行时间
        
        Args:
            task: 预测任务
            
        Returns:
            str: ISO格式的下次运行时间
        """
        now = datetime.now(timezone.utc)
        
        if task.trigger_type == "interval" and task.interval_sec:
            next_run = now + timedelta(seconds=task.interval_sec)
        elif task.trigger_type == "daily" and task.daily_time:
            parts = task.daily_time.split(":")
            if len(parts) == 2:
                hour, minute = int(parts[0]), int(parts[1])
                next_run = now.replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )
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
        """
        获取项目的预测任务
        
        Args:
            project_id: 项目ID
            
        Returns:
            list[dict]: 任务列表
        """
        tasks = self._store.load_tasks(project_id)
        return [t.model_dump() for t in tasks]
    
    def delete_prediction_task(self, project_id: str, task_id: str) -> dict:
        """
        删除预测任务
        
        Args:
            project_id: 项目ID
            task_id: 任务ID
            
        Returns:
            dict: 删除结果
        """
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
        
        由调度器定时调用。
        
        Returns:
            dict: 处理结果统计
        """
        processed = 0
        errors = []
        
        for project in self._store.list_projects():
            # 检查项目是否启用预测
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
                try:
                    next_run = datetime.fromisoformat(
                        task.next_run_at.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    continue
                
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
