"""
基础设施层：存储、外部 HTTP、向量、调度等实现。

- ``uap.infrastructure.persistence``：项目目录与 JSON 落盘
- ``uap.infrastructure.llm``：Ollama / 模型抽取
- ``uap.infrastructure.vector``：嵌入与检索
- ``uap.infrastructure.scheduler``：定时任务
"""

from uap.infrastructure.persistence import (
    ProjectStore,
    resolve_projects_root,
    user_workspace_dir,
)

__all__ = ["ProjectStore", "resolve_projects_root", "user_workspace_dir"]
