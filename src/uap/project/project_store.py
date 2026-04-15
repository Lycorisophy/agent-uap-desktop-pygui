"""
UAP 项目存储模块

负责项目的本地持久化存储：
- 项目目录结构：~/.uap/projects/{project_id}/
  - meta.json: 项目元数据
  - model.json: 系统模型
  - prediction_config.json: 预测配置
  - predictions/ 目录: 预测结果
  - data/ 目录: 原始数据
  - documents/ 目录: 导入的文档
  - messages.json: 对话历史
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .models import (
    PredictionConfig,
    PredictionResult,
    PredictionTask,
    Project,
    SystemModel,
)

if TYPE_CHECKING:
    from uap.config import UapConfig


class ProjectStore:
    """项目存储管理器"""
    
    PREDICTIONS_DIR = "predictions"
    DATA_DIR = "data"
    DOCUMENTS_DIR = "documents"
    MESSAGES_FILE = "messages.json"
    TASKS_FILE = "prediction_tasks.json"
    
    def __init__(self, root: Path | str, uap_cfg: Optional["UapConfig"] = None) -> None:
        self._root = Path(root) if isinstance(root, str) else root
        self._uap_cfg = uap_cfg
        self._root.mkdir(parents=True, exist_ok=True)
    
    @property
    def root(self) -> Path:
        return self._root
    
    def _project_dir(self, project_id: str) -> Path:
        """获取项目目录"""
        return self._root / project_id
    
    def _ensure_project_dir(self, project_id: str) -> Path:
        """确保项目目录存在"""
        d = self._project_dir(project_id)
        d.mkdir(parents=True, exist_ok=True)
        # 确保子目录存在
        (d / self.PREDICTIONS_DIR).mkdir(exist_ok=True)
        (d / self.DATA_DIR).mkdir(exist_ok=True)
        (d / self.DOCUMENTS_DIR).mkdir(exist_ok=True)
        return d
    
    # ============ 项目 CRUD ============
    
    def create_project(self, name: str, description: str = "", workspace: str = "") -> Project:
        """创建新项目"""
        project = Project(
            name=name,
            description=description,
            workspace=workspace or str(Path.cwd()),
        )
        d = self._ensure_project_dir(project.id)
        self._write_meta(d, project)
        self._write_messages(d, [])
        self._write_tasks(d, [])
        return project
    
    def get_project(self, project_id: str) -> Project:
        """获取项目"""
        d = self._project_dir(project_id)
        if not d.is_dir():
            raise FileNotFoundError(f"项目不存在: {project_id}")
        meta_path = d / "meta.json"
        if not meta_path.is_file():
            raise FileNotFoundError(f"项目元数据不存在: {project_id}")
        return Project.model_validate_json(meta_path.read_text(encoding="utf-8"))
    
    def update_project(self, project: Project) -> Project:
        """更新项目"""
        d = self._ensure_project_dir(project.id)
        project.touch()
        self._write_meta(d, project)
        return project
    
    def delete_project(self, project_id: str) -> None:
        """删除项目"""
        d = self._project_dir(project_id)
        if d.is_dir():
            shutil.rmtree(d)
    
    def list_projects(self) -> list[Project]:
        """列出所有项目"""
        projects = []
        if not self._root.is_dir():
            return projects
        for p in sorted(self._root.iterdir(), key=lambda x: x.name):
            if not p.is_dir():
                continue
            meta_path = p / "meta.json"
            if not meta_path.is_file():
                continue
            try:
                project = Project.model_validate_json(meta_path.read_text(encoding="utf-8"))
                projects.append(project)
            except Exception:
                continue
        # 按更新时间排序
        projects.sort(key=lambda x: x.updated_at or "", reverse=True)
        return projects
    
    def search_projects(self, query: str) -> list[Project]:
        """搜索项目"""
        q = query.lower().strip()
        if not q:
            return self.list_projects()
        results = []
        for p in self.list_projects():
            if q in p.name.lower() or q in (p.description or "").lower():
                results.append(p)
        return results
    
    # ============ 系统模型 ============
    
    def save_model(self, project_id: str, model: SystemModel) -> None:
        """保存系统模型"""
        d = self._ensure_project_dir(project_id)
        model.updated_at = datetime.now(timezone.utc).isoformat()
        (d / "model.json").write_text(
            model.model_dump_json(ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    
    def load_model(self, project_id: str) -> Optional[SystemModel]:
        """加载系统模型"""
        d = self._project_dir(project_id)
        model_path = d / "model.json"
        if not model_path.is_file():
            return None
        return SystemModel.model_validate_json(model_path.read_text(encoding="utf-8"))
    
    # ============ 预测配置 ============
    
    def save_prediction_config(self, project_id: str, config: PredictionConfig) -> None:
        """保存预测配置"""
        d = self._ensure_project_dir(project_id)
        (d / "prediction_config.json").write_text(
            config.model_dump_json(ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    
    def load_prediction_config(self, project_id: str) -> PredictionConfig:
        """加载预测配置"""
        d = self._project_dir(project_id)
        config_path = d / "prediction_config.json"
        if not config_path.is_file():
            return PredictionConfig()
        return PredictionConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
    
    # ============ 预测任务 ============
    
    def save_tasks(self, project_id: str, tasks: list[PredictionTask]) -> None:
        """保存预测任务列表"""
        d = self._ensure_project_dir(project_id)
        self._write_tasks(d, tasks)
    
    def load_tasks(self, project_id: str) -> list[PredictionTask]:
        """加载预测任务列表"""
        d = self._project_dir(project_id)
        tasks_path = d / self.TASKS_FILE
        if not tasks_path.is_file():
            return []
        try:
            data = json.loads(tasks_path.read_text(encoding="utf-8"))
            return [PredictionTask.model_validate(t) for t in data.get("tasks", [])]
        except Exception:
            return []
    
    def _write_tasks(self, d: Path, tasks: list[PredictionTask]) -> None:
        """写入任务文件"""
        (d / self.TASKS_FILE).write_text(
            json.dumps({"tasks": [t.model_dump() for t in tasks]}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    
    # ============ 预测结果 ============
    
    def save_prediction_result(self, project_id: str, result: PredictionResult) -> None:
        """保存预测结果"""
        d = self._ensure_project_dir(project_id)
        results_dir = d / self.PREDICTIONS_DIR
        result_file = results_dir / f"{result.id}.json"
        result_file.write_text(
            result.model_dump_json(ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        # 更新索引
        self._update_results_index(d, result)
    
    def load_prediction_result(self, project_id: str, result_id: str) -> Optional[PredictionResult]:
        """加载预测结果"""
        d = self._project_dir(project_id)
        result_file = d / self.PREDICTIONS_DIR / f"{result_id}.json"
        if not result_file.is_file():
            return None
        return PredictionResult.model_validate_json(result_file.read_text(encoding="utf-8"))
    
    def list_prediction_results(
        self, 
        project_id: str, 
        limit: int = 100,
        offset: int = 0
    ) -> list[PredictionResult]:
        """列出预测结果（按时间倒序）"""
        d = self._project_dir(project_id)
        results_dir = d / self.PREDICTIONS_DIR
        if not results_dir.is_dir():
            return []
        
        results = []
        for f in sorted(results_dir.glob("*.json"), key=lambda x: x.name, reverse=True):
            try:
                r = PredictionResult.model_validate_json(f.read_text(encoding="utf-8"))
                results.append(r)
            except Exception:
                continue
        
        # 分页
        return results[offset:offset + limit]
    
    def delete_prediction_result(self, project_id: str, result_id: str) -> None:
        """删除预测结果"""
        d = self._project_dir(project_id)
        result_file = d / self.PREDICTIONS_DIR / f"{result_id}.json"
        if result_file.is_file():
            result_file.unlink()
        # 更新索引
        self._remove_from_results_index(d, result_id)
    
    def _update_results_index(self, d: Path, result: PredictionResult) -> None:
        """更新结果索引"""
        index_file = d / self.PREDICTIONS_DIR / "_index.json"
        try:
            if index_file.is_file():
                index = json.loads(index_file.read_text(encoding="utf-8"))
            else:
                index = {"results": []}
        except Exception:
            index = {"results": []}
        
        # 移除旧记录
        index["results"] = [r for r in index.get("results", []) if r.get("id") != result.id]
        # 添加新记录
        index["results"].insert(0, {
            "id": result.id,
            "created_at": result.created_at,
            "project_id": result.project_id,
            "status": result.status,
        })
        # 限制索引大小
        index["results"] = index["results"][:1000]
        
        index_file.write_text(
            json.dumps(index, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    
    def _remove_from_results_index(self, d: Path, result_id: str) -> None:
        """从索引中移除结果"""
        index_file = d / self.PREDICTIONS_DIR / "_index.json"
        if not index_file.is_file():
            return
        try:
            index = json.loads(index_file.read_text(encoding="utf-8"))
            index["results"] = [r for r in index.get("results", []) if r.get("id") != result_id]
            index_file.write_text(
                json.dumps(index, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass
    
    # ============ 对话消息 ============
    
    def save_messages(self, project_id: str, messages: list[dict]) -> None:
        """保存对话消息"""
        d = self._ensure_project_dir(project_id)
        self._write_messages(d, messages)
    
    def load_messages(self, project_id: str) -> list[dict]:
        """加载对话消息"""
        d = self._project_dir(project_id)
        messages_path = d / self.MESSAGES_FILE
        if not messages_path.is_file():
            return []
        try:
            data = json.loads(messages_path.read_text(encoding="utf-8"))
            return data.get("messages", [])
        except Exception:
            return []
    
    def _write_messages(self, d: Path, messages: list[dict]) -> None:
        """写入消息文件"""
        (d / self.MESSAGES_FILE).write_text(
            json.dumps({"messages": messages}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    
    # ============ 项目元数据 ============
    
    def _write_meta(self, d: Path, project: Project) -> None:
        """写入项目元数据"""
        (d / "meta.json").write_text(
            project.model_dump_json(ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    
    # ============ 工作区文件 ============
    
    def get_workspace_path(self, project_id: str) -> Path:
        """获取项目工作区路径"""
        d = self._ensure_project_dir(project_id)
        return d / self.DATA_DIR
    
    def get_documents_path(self, project_id: str) -> Path:
        """获取文档目录路径"""
        d = self._ensure_project_dir(project_id)
        return d / self.DOCUMENTS_DIR


def resolve_projects_root(uap_cfg: Optional["UapConfig"] = None) -> Path:
    """解析项目根目录"""
    if uap_cfg and uap_cfg.storage.projects_root:
        return Path(uap_cfg.storage.projects_root).expanduser().resolve()
    return (Path.home() / ".uap" / "projects").resolve()
