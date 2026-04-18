"""
数据访问层：项目目录、JSON 落盘。

历史路径 ``uap.infrastructure.persistence`` 转发至本包。
"""

from uap.persistence.project_store import (
    ProjectStore,
    resolve_projects_root,
    user_workspace_dir,
)

__all__ = ["ProjectStore", "resolve_projects_root", "user_workspace_dir"]
