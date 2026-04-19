"""
结构化日志辅助：便于检索 project_id / session_id 等字段（P3 可观测性基线）。
"""

from __future__ import annotations

import logging
from typing import Any


def log_with_context(
    logger: logging.Logger,
    level: int,
    msg: str,
    *,
    exc_info: bool | None = None,
    **fields: Any,
) -> None:
    """在消息后缀附加 ``key=value`` 片段（值 None 跳过）。"""
    parts = [f"{k}={v}" for k, v in sorted(fields.items()) if v is not None and str(v) != ""]
    suffix = (" | " + " ".join(parts)) if parts else ""
    logger.log(level, "%s%s", msg, suffix, exc_info=exc_info)
