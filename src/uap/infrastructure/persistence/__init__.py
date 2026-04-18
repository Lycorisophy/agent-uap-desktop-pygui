"""兼容入口：数据访问实现位于 ``uap.persistence``。"""

from uap.persistence import (
    ProjectStore,
    resolve_projects_root,
    user_workspace_dir,
)

__all__ = ["ProjectStore", "resolve_projects_root", "user_workspace_dir"]
