"""兼容入口：实现位于 ``uap.core.action.plan``。"""

import uap.core.action.plan as _impl

from uap.core.action.plan import *  # noqa: F403

__all__ = list(_impl.__all__)
