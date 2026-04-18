"""兼容入口：实现位于 ``uap.core.action.react``。"""

import uap.core.action.react as _impl

from uap.core.action.react import *  # noqa: F403

__all__ = list(_impl.__all__)
