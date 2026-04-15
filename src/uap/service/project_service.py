"""
UAP 项目服务

管理项目的创建、对话、建模等核心功能
集成LLM模型提取能力
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from uap.config import UapConfig
from uap.llm import ModelExtractor, create_default_extractor
from uap.project.models import (
    ModelSource,
    PredictionConfig,
    Project,
    ProjectStatus,
    SystemModel,
)
from uap.project.project_store import ProjectStore

_LOG = logging.getLogger("uap.project_service")


class ProjectService:
    """
    项目服务
    
    提供项目管理、模型提取、对话管理等核心功能。
    集成LLM能力，支持从对话或文档中自动提取系统模型。
    """
    
    def __init__(
        self,
        store: ProjectStore,
        cfg: UapConfig,
        extractor: Optional[ModelExtractor] = None
    ) -> None:
        """
        初始化项目服务
        
        Args:
            store: 项目存储实例
            cfg: 应用配置
            extractor: 模型提取器，默认创建Ollama提取器
        """
        self._store = store
        self._cfg = cfg
        # 使用配置中的模型创建提取器
        from uap.llm.ollama_client import OllamaClient, OllamaConfig
        from uap.llm.model_extractor import ModelExtractor
        ollama_cfg = OllamaConfig(
            base_url=cfg.llm.base_url,
            model=cfg.llm.model,
        )
        ollama_client = OllamaClient(ollama_cfg)
        self._extractor = extractor or ModelExtractor(ollama_client)
    
    def refresh_extractor(self):
        """重新创建提取器以使用最新配置"""
        from uap.llm.ollama_client import OllamaClient, OllamaConfig
        from uap.llm.model_extractor import ModelExtractor
        ollama_cfg = OllamaConfig(
            base_url=self._cfg.llm.base_url,
            model=self._cfg.llm.model,
        )
        ollama_client = OllamaClient(ollama_cfg)
        self._extractor = ModelExtractor(ollama_client)
        _LOG = logging.getLogger("uap.project_service")
        _LOG.info(f"Extractor refreshed with model={self._cfg.llm.model}")
    
    @property
    def store(self) -> ProjectStore:
        """获取项目存储"""
        return self._store
    
    @property
    def extractor(self) -> ModelExtractor:
        """获取模型提取器"""
        return self._extractor
    
    def set_extractor(self, extractor: ModelExtractor):
        """
        设置模型提取器
        
        Args:
            extractor: 新的模型提取器实例
        """
        self._extractor = extractor
    
    # ============ 项目管理 ============
    
    def create_project(
        self,
        name: str,
        description: str = "",
        workspace: str = ""
    ) -> dict:
        """
        创建新项目
        
        Args:
            name: 项目名称
            description: 项目描述
            workspace: 工作空间路径
            
        Returns:
            dict: 创建结果，包含project和project_id
        """
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
        """
        获取项目信息
        
        Args:
            project_id: 项目ID
            
        Returns:
            dict: 项目信息和系统模型
        """
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
        """
        列出所有项目
        
        Returns:
            list[dict]: 项目摘要列表
        """
        projects = self._store.list_projects()
        return [p.to_summary() for p in projects]
    
    def search_projects(self, query: str) -> list[dict]:
        """
        搜索项目
        
        Args:
            query: 搜索关键词
            
        Returns:
            list[dict]: 匹配的项目列表
        """
        projects = self._store.search_projects(query)
        return [p.to_summary() for p in projects]
    
    def delete_project(self, project_id: str) -> dict:
        """
        删除项目
        
        Args:
            project_id: 项目ID
            
        Returns:
            dict: 删除结果
        """
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
        """
        更新项目信息
        
        Args:
            project_id: 项目ID
            name: 新名称
            description: 新描述
            tags: 新标签
            
        Returns:
            dict: 更新结果
        """
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
        """
        保存系统模型
        
        Args:
            project_id: 项目ID
            model: 系统模型对象
            
        Returns:
            dict: 保存结果
        """
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
        """
        加载系统模型
        
        Args:
            project_id: 项目ID
            
        Returns:
            dict: 模型数据
        """
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
        
        使用LLM分析对话历史和用户描述，自动提取系统的数学模型。
        
        Args:
            project_id: 项目ID
            messages: 对话历史消息列表
            user_prompt: 用户当前的系统描述
            
        Returns:
            dict: 提取结果，包含模型数据
        """
        try:
            project = self._store.get_project(project_id)
            
            _LOG.info("开始从对话提取模型: project=%s", project_id)
            
            # 调用LLM提取模型
            result = self._extractor.extract_from_conversation(
                messages=messages,
                user_prompt=user_prompt
            )
            
            if not result.success:
                _LOG.warning("模型提取失败: %s", result.error)
                return {
                    "ok": False,
                    "error": result.error or "模型提取失败"
                }
            
            model = result.model
            model.name = f"{project.name} - 对话建模"
            model.source = ModelSource.LLM_EXTRACTED
            model.modeling_prompt = user_prompt
            
            # 验证模型
            is_valid, errors = self._extractor.validate_model(model)
            if not is_valid:
                _LOG.warning("模型验证失败: %s", errors)
                return {
                    "ok": False,
                    "error": f"模型验证失败: {', '.join(errors)}"
                }
            
            # 保存模型和项目
            project.system_model = model
            project.status = ProjectStatus.MODELING
            project = self._store.update_project(project)
            self._store.save_model(project_id, model)
            
            _LOG.info(
                "模型提取成功: project=%s, variables=%d, relations=%d, confidence=%.2f",
                project_id, len(model.variables), len(model.relations), model.confidence
            )
            
            return {
                "ok": True,
                "model": model.model_dump(),
                "reasoning": result.reasoning,
                "message": f"成功提取模型，包含{len(model.variables)}个变量和{len(model.relations)}个关系"
            }
            
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
        except Exception as e:
            _LOG.error("模型提取异常: %s", str(e))
            return {"ok": False, "error": f"模型提取异常: {str(e)}"}
    
    def import_model_from_document(
        self,
        project_id: str,
        document_content: str,
        document_name: str = "",
    ) -> dict:
        """
        从文档导入系统模型
        
        使用LLM分析文档内容，自动提取系统的数学模型。
        
        Args:
            project_id: 项目ID
            document_content: 文档文本内容
            document_name: 文档名称
            
        Returns:
            dict: 提取结果，包含模型数据
        """
        try:
            project = self._store.get_project(project_id)
            
            _LOG.info(
                "开始从文档提取模型: project=%s, doc=%s",
                project_id, document_name
            )
            
            # 调用LLM提取模型
            result = self._extractor.extract_from_document(
                document_content=document_content,
                document_name=document_name
            )
            
            if not result.success:
                _LOG.warning("文档模型提取失败: %s", result.error)
                return {
                    "ok": False,
                    "error": result.error or "文档模型提取失败"
                }
            
            model = result.model
            model.name = f"{project.name} - 文档导入"
            model.source = ModelSource.LLM_EXTRACTED
            model.modeling_prompt = f"文档: {document_name}"
            
            # 验证模型
            is_valid, errors = self._extractor.validate_model(model)
            if not is_valid:
                _LOG.warning("模型验证失败: %s", errors)
                return {
                    "ok": False,
                    "error": f"模型验证失败: {', '.join(errors)}"
                }
            
            # 保存模型和项目
            project.system_model = model
            project.status = ProjectStatus.MODELING
            project = self._store.update_project(project)
            self._store.save_model(project_id, model)
            
            _LOG.info(
                "文档模型提取成功: project=%s, variables=%d, relations=%d",
                project_id, len(model.variables), len(model.relations)
            )
            
            return {
                "ok": True,
                "model": model.model_dump(),
                "reasoning": result.reasoning,
                "message": f"成功从文档'{document_name}'提取模型"
            }
            
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
        except Exception as e:
            _LOG.error("文档模型提取异常: %s", str(e))
            return {"ok": False, "error": f"文档模型提取异常: {str(e)}"}
    
    # ============ 预测配置 ============
    
    def save_prediction_config(
        self,
        project_id: str,
        config: PredictionConfig,
    ) -> dict:
        """
        保存预测配置
        
        Args:
            project_id: 项目ID
            config: 预测配置对象
            
        Returns:
            dict: 保存结果
        """
        try:
            project = self._store.get_project(project_id)
            project.prediction_config = config
            project = self._store.update_project(project)
            self._store.save_prediction_config(project_id, config)
            _LOG.info(
                "保存预测配置: project=%s, frequency=%ds, horizon=%ds",
                project_id, config.frequency_sec, config.horizon_sec
            )
            return {"ok": True}
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
    
    def load_prediction_config(self, project_id: str) -> dict:
        """
        加载预测配置
        
        Args:
            project_id: 项目ID
            
        Returns:
            dict: 配置数据
        """
        config = self._store.load_prediction_config(project_id)
        return {"ok": True, "config": config.model_dump()}
    
    # ============ 对话 ============
    
    def get_messages(self, project_id: str) -> list[dict]:
        """
        获取对话消息
        
        Args:
            project_id: 项目ID
            
        Returns:
            list[dict]: 消息列表
        """
        return self._store.load_messages(project_id)
    
    def save_message(
        self,
        project_id: str,
        role: str,
        content: str,
    ) -> dict:
        """
        保存对话消息
        
        Args:
            project_id: 项目ID
            role: 消息角色（user/assistant）
            content: 消息内容
            
        Returns:
            dict: 保存结果
        """
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
        """
        追加助手消息
        
        Args:
            project_id: 项目ID
            content: 助手回复内容
            
        Returns:
            dict: 保存结果
        """
        return self.save_message(project_id, "assistant", content)
    
    def clear_messages(self, project_id: str) -> dict:
        """
        清空对话历史
        
        Args:
            project_id: 项目ID
            
        Returns:
            dict: 清空结果
        """
        try:
            self._store.save_messages(project_id, [])
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}
