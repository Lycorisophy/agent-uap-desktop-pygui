"""
基础设施层（过渡兼容）：存储、外部 HTTP、向量、调度等。

- 数据访问主入口：``uap.persistence``（本包 ``persistence`` 子模块转发）
- LLM 防腐层主入口：``uap.adapters.llm``（本包 ``llm`` 子模块转发）
- ``uap.infrastructure.vector``：嵌入与检索
- ``uap.infrastructure.scheduler``：定时任务
"""

from uap.infrastructure.persistence import (
    ProjectStore,
    resolve_projects_root,
    user_workspace_dir,
)

__all__ = ["ProjectStore", "resolve_projects_root", "user_workspace_dir"]
