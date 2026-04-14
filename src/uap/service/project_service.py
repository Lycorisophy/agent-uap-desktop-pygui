"""
UAP 项目服务

管理项目的创建、对话、建模等核心功能
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.uap.config import UapConfig
from src.uap.project.models import (
    ModelSource,
    PredictionConfig,
    Project,
    ProjectStatus,
    SystemModel,
)
from src.uap.project.project_store import ProjectStore, resolve_projects_root

_LOG = logging.getLogger("uap.project_service")


class ProjectService:
    """项目服务"""
    
    def __init__(self, store: ProjectStore, cfg: UapConfig) -> None:
        self._store = store
        self._cfg = cfg
    
    @property
    def store(self) -> ProjectStore:
        return self._store
    
    # ============ 项目管理 ============
    
    def create_project(
        self,
        name: str,
        description: str = "",
        workspace: str = ""
    ) -> dict:
        """创建新项目"""
        if not name.strip():
            return {"ok": False, "error": "项目名称不能为空"}
        
        project = self._store.create_project(
            name=name.strip(),
            description=description.strip(),
            workspace=workspace.strip()
        )
        
        _LOG.info("创建项目: %s (id=%s)", project.name, project.id)
        
        return {
            "ok": True,
            "project": project.to_summary(),
            "project_id": project.id,
        }
    
    def get_project(self, project_id: str) -> dict:
        """获取项目"""
        try:
            project = self._store.get_project(project_id)
            return {
                "ok": True,
                "project": project.model_dump(),
                "system_model": project.system_model.model_dump() if project.system_model else None,
            }
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
    
    def list_projects(self) -> list[dict]:
        """列出所有项目"""
        projects = self._store.list_projects()
        return [p.to_summary() for p in projects]
    
    def search_projects(self, query: str) -> list[dict]:
        """搜索项目"""
        projects = self._store.search_projects(query)
        return [p.to_summary() for p in projects]
    
    def delete_project(self, project_id: str) -> dict:
        """删除项目"""
        try:
            self._store.delete_project(project_id)
            _LOG.info("删除项目: %s", project_id)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def update_project(
        self,
        project_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> dict:
        """更新项目"""
        try:
            project = self._store.get_project(project_id)
            if name is not None:
                project.name = name.strip()
            if description is not None:
                project.description = description.strip()
            if tags is not None:
                project.tags = tags
            
            project = self._store.update_project(project)
            return {"ok": True, "project": project.to_summary()}
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
    
    # ============ 系统模型 ============
    
    def save_model(self, project_id: str, model: SystemModel) -> dict:
        """保存系统模型"""
        try:
            project = self._store.get_project(project_id)
            project.system_model = model
            project = self._store.update_project(project)
            self._store.save_model(project_id, model)
            _LOG.info("保存模型: project=%s, model_id=%s", project_id, model.id)
            return {"ok": True, "model_id": model.id}
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
    
    def load_model(self, project_id: str) -> dict:
        """加载系统模型"""
        model = self._store.load_model(project_id)
        if model is None:
            return {"ok": False, "error": "模型不存在"}
        return {"ok": True, "model": model.model_dump()}
    
    def extract_model_from_conversation(
        self,
        project_id: str,
        messages: list[dict],
        user_prompt: str,
    ) -> dict:
        """
        从对话中提取系统模型
        
        这是一个简化实现，实际应该调用 LLM 进行抽取
        """
        try:
            project = self._store.get_project(project_id)
            
            # TODO: 调用 LLM 进行模型抽取
            # 这里先创建一个占位模型
            model = SystemModel(
                name=f"{project.name} - 自动建模",
                description="从对话中自动提取的系统模型",
                source=ModelSource.CONVERSATION,
                modeling_prompt=user_prompt,
            )
            
            project.system_model = model
            project.status = ProjectStatus.IDLE
            project = self._store.update_project(project)
            self._store.save_model(project_id, model)
            
            return {
                "ok": True,
                "model": model.model_dump(),
                "message": "模型已从对话中提取"
            }
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
    
    def import_model_from_document(
        self,
        project_id: str,
        document_content: str,
        document_name: str = "",
    ) -> dict:
        """
        从文档导入系统模型
        
        这是一个简化实现，实际应该调用 LLM 从文档中抽取模型
        """
        try:
            project = self._store.get_project(project_id)
            
            # TODO: 调用 LLM 从文档中抽取模型
            model = SystemModel(
                name=f"{project.name} - 文档导入",
                description=f"从文档 {document_name} 导入的模型",
                source=ModelSource.DOCUMENT,
                modeling_prompt=f"文档内容: {document_content[:1000]}...",
            )
            
            project.system_model = model
            project.status = ProjectStatus.IDLE
            project = self._store.update_project(project)
            self._store.save_model(project_id, model)
            
            return {
                "ok": True,
                "model": model.model_dump(),
                "message": f"模型已从文档 {document_name} 中提取"
            }
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
    
    # ============ 预测配置 ============
    
    def save_prediction_config(
        self,
        project_id: str,
        config: PredictionConfig,
    ) -> dict:
        """保存预测配置"""
        try:
            project = self._store.get_project(project_id)
            project.prediction_config = config
            project = self._store.update_project(project)
            self._store.save_prediction_config(project_id, config)
            _LOG.info("保存预测配置: project=%s, frequency=%ds, horizon=%ds",
                      project_id, config.frequency_sec, config.horizon_sec)
            return {"ok": True}
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
    
    def load_prediction_config(self, project_id: str) -> dict:
        """加载预测配置"""
        config = self._store.load_prediction_config(project_id)
        return {"ok": True, "config": config.model_dump()}
    
    # ============ 对话 ============
    
    def get_messages(self, project_id: str) -> list[dict]:
        """获取对话消息"""
        return self._store.load_messages(project_id)
    
    def save_message(
        self,
        project_id: str,
        role: str,
        content: str,
    ) -> dict:
        """保存对话消息"""
        try:
            messages = self._store.load_messages(project_id)
            messages.append({
                "role": role,
                "content": content,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            self._store.save_messages(project_id, messages)
            return {"ok": True, "message_count": len(messages)}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def append_assistant_message(self, project_id: str, content: str) -> dict:
        """追加助手消息"""
        return self.save_message(project_id, "assistant", content)
    
    def clear_messages(self, project_id: str) -> dict:
        """清空对话历史"""
        try:
            self._store.save_messages(project_id, [])
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}
