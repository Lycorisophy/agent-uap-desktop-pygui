"""项目工作区路径规范化：避免模型把「项目 ID/文件夹名」重复拼进相对路径。"""

from __future__ import annotations

import os


def normalize_relative_path_for_project(user_path: str, project_folder: str) -> str:
    """
    将相对项目根的路径规范化。

    常见错误：``project_folder`` 已是 ``.../projects/<id>``，模型仍传入
    ``<id>/data`` 或 ``<id>\\data``，若直接 ``join`` 会得到 ``.../<id>/<id>/data``。

    若首段路径分量与项目根目录名相同，则去掉该重复前缀（可多次剥离）。
    """
    raw = (user_path or "").strip()
    if not raw:
        return raw
    if os.path.isabs(raw):
        return raw

    s = raw.replace("\\", "/").strip()
    while s.startswith("./"):
        s = s[2:]

    try:
        base = os.path.basename(os.path.normpath(project_folder))
    except (OSError, TypeError, ValueError):
        base = ""

    if not base:
        return raw

    parts = [p for p in s.split("/") if p and p != "."]
    while parts and parts[0] == base:
        parts = parts[1:]

    if not parts:
        return "."
    return "/".join(parts)
