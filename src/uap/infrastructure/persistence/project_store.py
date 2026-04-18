"""兼容入口：实现位于 ``uap.persistence.project_store``。"""

from uap.persistence.project_store import (
    ProjectStore,
    resolve_projects_root,
    user_workspace_dir,
)

__all__ = ["ProjectStore", "resolve_projects_root", "user_workspace_dir"]
