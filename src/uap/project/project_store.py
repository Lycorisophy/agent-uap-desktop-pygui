"""兼容入口：实现已迁至 ``uap.infrastructure.persistence``。"""

from uap.infrastructure.persistence.project_store import (
    ProjectStore,
    resolve_projects_root,
    user_workspace_dir,
)

__all__ = ["ProjectStore", "resolve_projects_root", "user_workspace_dir"]
