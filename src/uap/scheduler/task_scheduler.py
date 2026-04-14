"""
UAP 调度器模块
基于如意72 scheduler 扩展，支持预测任务的定时执行
"""

import json
import time
import threading
import uuid
from datetime import datetime, timedelta
from typing import Optional, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum

from uap.project.models import PredictionTask, TaskStatus, TriggerType


@dataclass
class SchedulerConfig:
    """调度器配置"""
    check_interval: int = 10  # 检查间隔（秒）
    max_concurrent_tasks: int = 3  # 最大并发任务数
    task_timeout: int = 300  # 任务超时时间（秒）
    retry_times: int = 3  # 重试次数
    retry_interval: int = 60  # 重试间隔（秒）
    enabled: bool = True  # 是否启用调度器


class TaskScheduler:
    """
    预测任务调度器
    支持定时任务、间隔任务、一次性任务
    """

    def __init__(self, config: Optional[SchedulerConfig] = None):
        self.config = config or SchedulerConfig()
        self._tasks: dict[str, PredictionTask] = {}
        self._running = False
        self._scheduler_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._task_callback: Optional[Callable] = None
        self._tasks_file: Optional[str] = None

    def set_task_callback(self, callback: Callable[[str], None]):
        """设置任务执行回调函数"""
        self._task_callback = callback

    def set_tasks_file(self, path: str):
        """设置任务持久化文件路径"""
        self._tasks_file = path

    def add_interval_task(
        self,
        project_id: str,
        interval_sec: int,
        task_id: Optional[str] = None
    ) -> PredictionTask:
        """添加间隔任务（周期预测）"""
        task_id = task_id or str(uuid.uuid4())
        now = datetime.now()

        task = PredictionTask(
            id=task_id,
            project_id=project_id,
            trigger_type=TriggerType.INTERVAL,
            interval_seconds=interval_sec,
            status=TaskStatus.PENDING,
            created_at=now.isoformat(),
            next_run_at=(now + timedelta(seconds=interval_sec)).isoformat()
        )

        with self._lock:
            self._tasks[task_id] = task

        self._save_tasks()
        return task

    def add_cron_task(
        self,
        project_id: str,
        cron_expression: str,
        task_id: Optional[str] = None
    ) -> PredictionTask:
        """添加Cron任务"""
        task_id = task_id or str(uuid.uuid4())
        now = datetime.now()

        task = PredictionTask(
            id=task_id,
            project_id=project_id,
            trigger_type=TriggerType.CRON,
            cron_expression=cron_expression,
            status=TaskStatus.PENDING,
            created_at=now.isoformat(),
            next_run_at=self._calc_next_cron_run(cron_expression, now)
        )

        with self._lock:
            self._tasks[task_id] = task

        self._save_tasks()
        return task

    def add_one_time_task(
        self,
        project_id: str,
        run_at: datetime,
        task_id: Optional[str] = None
    ) -> PredictionTask:
        """添加一次性任务"""
        task_id = task_id or str(uuid.uuid4())

        task = PredictionTask(
            id=task_id,
            project_id=project_id,
            trigger_type=TriggerType.ONE_TIME,
            status=TaskStatus.PENDING,
            created_at=datetime.now().isoformat(),
            next_run_at=run_at.isoformat()
        )

        with self._lock:
            self._tasks[task_id] = task

        self._save_tasks()
        return task

    def remove_task(self, task_id: str) -> bool:
        """移除任务"""
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                self._save_tasks()
                return True
        return False

    def get_task(self, task_id: str) -> Optional[PredictionTask]:
        """获取任务"""
        with self._lock:
            return self._tasks.get(task_id)

    def get_project_tasks(self, project_id: str) -> list[PredictionTask]:
        """获取项目的所有任务"""
        with self._lock:
            return [t for t in self._tasks.values() if t.project_id == project_id]

    def pause_task(self, task_id: str) -> bool:
        """暂停任务"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.status == TaskStatus.RUNNING:
                task.status = TaskStatus.PAUSED
                self._save_tasks()
                return True
        return False

    def resume_task(self, task_id: str) -> bool:
        """恢复任务"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.status == TaskStatus.PAUSED:
                task.status = TaskStatus.PENDING
                task.next_run_at = datetime.now().isoformat()
                self._save_tasks()
                return True
        return False

    def start(self):
        """启动调度器"""
        if self._running:
            return

        self._running = True
        self._scheduler_thread = threading.Thread(
            target=self._run_scheduler_loop,
            daemon=True
        )
        self._scheduler_thread.start()

    def stop(self):
        """停止调度器"""
        self._running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5)
            self._scheduler_thread = None

    def _run_scheduler_loop(self):
        """调度器主循环"""
        while self._running:
            try:
                self._process_due_tasks()
            except Exception as e:
                print(f"Scheduler error: {e}")

            time.sleep(self.config.check_interval)

    def _process_due_tasks(self):
        """处理到期的任务"""
        now = datetime.now()

        with self._lock:
            # 统计运行中的任务数
            running_count = sum(
                1 for t in self._tasks.values()
                if t.status == TaskStatus.RUNNING
            )

            for task_id, task in self._tasks.items():
                # 跳过非待执行状态的任务
                if task.status not in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                    continue

                # 检查是否到期
                if not self._is_due(task, now):
                    continue

                # 检查并发限制
                if running_count >= self.config.max_concurrent_tasks:
                    break

                # 执行任务
                self._execute_task(task)
                running_count += 1

    def _is_due(self, task: PredictionTask, now: datetime) -> bool:
        """检查任务是否到期"""
        if not task.next_run_at:
            return False

        try:
            next_run = datetime.fromisoformat(task.next_run_at)
            return now >= next_run
        except (ValueError, TypeError):
            return False

    def _execute_task(self, task: PredictionTask):
        """执行任务"""
        print(f"Executing prediction task: {task.id} for project: {task.project_id}")

        task.status = TaskStatus.RUNNING
        task.run_count += 1
        task.last_run_at = datetime.now().isoformat()
        self._save_tasks()

        try:
            # 调用回调函数执行预测
            if self._task_callback:
                self._task_callback(task.project_id)

            # 更新下次执行时间
            if task.trigger_type == TriggerType.INTERVAL:
                task.next_run_at = (
                    datetime.now() + timedelta(seconds=task.interval_seconds)
                ).isoformat()
                task.status = TaskStatus.PENDING
            elif task.trigger_type == TriggerType.CRON:
                task.next_run_at = self._calc_next_cron_run(
                    task.cron_expression,
                    datetime.now()
                )
                task.status = TaskStatus.PENDING
            else:
                # 一次性任务完成后标记为完成
                task.status = TaskStatus.COMPLETED

            task.last_error = None

        except Exception as e:
            print(f"Task execution error: {e}")
            task.last_error = str(e)

            # 检查是否需要重试
            if task.run_count < self.config.retry_times:
                task.status = TaskStatus.PENDING
                task.next_run_at = (
                    datetime.now() + timedelta(seconds=self.config.retry_interval)
                ).isoformat()
            else:
                task.status = TaskStatus.FAILED

        self._save_tasks()

    def _calc_next_cron_run(self, cron_expr: str, now: datetime) -> str:
        """
        计算下次Cron执行时间
        简化实现：支持标准5段cron格式
        分钟 小时 日 月 周
        """
        # 简化实现：每分钟检查一次
        return (now + timedelta(minutes=1)).isoformat()

    def _save_tasks(self):
        """保存任务列表到文件"""
        if not self._tasks_file:
            return

        try:
            with open(self._tasks_file, 'w', encoding='utf-8') as f:
                tasks_data = {
                    tid: asdict(task) for tid, task in self._tasks.items()
                }
                json.dump(tasks_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Failed to save tasks: {e}")

    def load_tasks(self):
        """从文件加载任务列表"""
        if not self._tasks_file:
            return

        try:
            with open(self._tasks_file, 'r', encoding='utf-8') as f:
                tasks_data = json.load(f)

            with self._lock:
                for tid, data in tasks_data.items():
                    # 转换trigger_type为枚举
                    if 'trigger_type' in data:
                        data['trigger_type'] = TriggerType(data['trigger_type'])
                    if 'status' in data:
                        data['status'] = TaskStatus(data['status'])
                    self._tasks[tid] = PredictionTask(**data)

        except (FileNotFoundError, json.JSONDecodeError):
            pass
        except Exception as e:
            print(f"Failed to load tasks: {e}")

    def get_status(self) -> dict:
        """获取调度器状态"""
        with self._lock:
            return {
                "running": self._running,
                "total_tasks": len(self._tasks),
                "pending": sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING),
                "running_count": sum(1 for t in self._tasks.values() if t.status == TaskStatus.RUNNING),
                "completed": sum(1 for t in self._tasks.values() if t.status == TaskStatus.COMPLETED),
                "failed": sum(1 for t in self._tasks.values() if t.status == TaskStatus.FAILED),
            }
