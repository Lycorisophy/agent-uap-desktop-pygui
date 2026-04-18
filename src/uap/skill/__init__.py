"""兼容入口：实现位于 ``uap.core.skills``。"""

import uap.core.skills as _core_skills

from uap.core.skills import *  # noqa: F403

__all__ = list(_core_skills.__all__)
