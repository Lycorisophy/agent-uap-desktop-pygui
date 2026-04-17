"""
项目工作区内的文件读写删改移技能（skill_id: win11_*）。

实现基于 pathlib/shutil，与操作系统解耦；命名 win11 表示在 Windows 11 桌面产品中使用。
所有路径必须解析到「项目根」之下，防止目录穿越；未来 MCP Server 可复用本模块内逻辑。
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from uap.react.project_path_utils import normalize_relative_path_for_project
from uap.skill.atomic_skills import AtomicSkill, SkillCategory, SkillComplexity, SkillMetadata

_LOG = logging.getLogger("uap.react.win11_fs")

# 与 file_access 同量级；写/改略放宽但仍防误传巨文件
_DEFAULT_MAX_READ = 1024 * 1024
_DEFAULT_MAX_WRITE = 4 * 1024 * 1024
# 递归删除时最多统计/处理的条目数，防止一次扫盘过久
_MAX_RMDIR_ENTRIES = 5000


def _count_walk_entries(root: Path) -> int:
    n = 0
    for _r, dirs, files in os.walk(root):
        n += len(dirs) + len(files)
        if n > _MAX_RMDIR_ENTRIES:
            return n
    return n


def resolve_project_path(project_root: Path, user_path: str) -> tuple[bool, str, Path | None]:
    """
    将用户给出的路径解析为项目根下的绝对路径。

    Returns:
        (ok, error_message, resolved_or_none)
    """
    raw = (user_path or "").strip()
    if not raw:
        return False, "路径不能为空", None
    try:
        root = project_root.resolve()
    except OSError as e:
        return False, f"项目根无效: {e}", None

    try:
        if Path(raw).is_absolute():
            cand = Path(raw).resolve()
        else:
            rel = normalize_relative_path_for_project(raw, str(root))
            cand = (root / rel).resolve()
    except OSError as e:
        return False, f"路径解析失败: {e}", None

    try:
        cand.relative_to(root)
    except ValueError:
        return False, "访问被拒绝：路径超出项目目录范围", None
    return True, "", cand


def _fail(msg: str) -> dict[str, Any]:
    return {"error": msg, "observation": f"操作失败：{msg}"}


class Win11ReadFileSkill(AtomicSkill):
    """读取项目内文本文件（二进制则返回十六进制摘要）。"""

    def __init__(self, project_root: Path):
        self._root = project_root
        meta = SkillMetadata(
            skill_id="win11_read_file",
            name="Win11 读文件",
            description=(
                "读取项目工作区内的文件内容。列目录请仍用 file_access(list)。"
                "写/删/改/移请用对应 win11_* 技能。"
            ),
            category=SkillCategory.TOOL,
            subcategory="file",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "description": "相对项目根或已落在项目内的绝对路径"},
                    "encoding": {"type": "string", "default": "utf-8"},
                    "max_bytes": {
                        "type": "integer",
                        "default": _DEFAULT_MAX_READ,
                        "description": "最多读取字节数",
                    },
                },
            },
            estimated_time=2,
            complexity=SkillComplexity.SIMPLE,
            provides_skills=["project_fs_read"],
        )
        super().__init__(meta)

    def execute(self, **kwargs) -> dict:
        path = kwargs.get("path", "")
        encoding = (kwargs.get("encoding") or "utf-8").strip() or "utf-8"
        try:
            max_bytes = int(kwargs.get("max_bytes", _DEFAULT_MAX_READ))
        except (TypeError, ValueError):
            max_bytes = _DEFAULT_MAX_READ
        max_bytes = max(256, min(max_bytes, 16 * 1024 * 1024))

        ok, err, resolved = resolve_project_path(self._root, str(path))
        if not ok or resolved is None:
            return _fail(err)
        if not resolved.exists():
            return _fail("文件或路径不存在")
        if not resolved.is_file():
            return _fail("路径不是文件")
        size = resolved.stat().st_size
        if size > max_bytes:
            return _fail(f"文件过大：{size} > 限制 {max_bytes} 字节")
        try:
            text = resolved.read_text(encoding=encoding, errors="strict")
        except UnicodeDecodeError:
            data = resolved.read_bytes()[:2000]
            return {
                "content": f"[二进制，以下为 hex 前 {len(data)} 字节]\n{data.hex()}",
                "is_binary": True,
                "observation": f"已按二进制读取摘要：{resolved.name}",
            }
        except OSError as e:
            return _fail(str(e))
        return {
            "content": text,
            "file_size": size,
            "observation": f"成功读取 {resolved.name}（{size} 字节）",
        }


class Win11WriteFileSkill(AtomicSkill):
    """创建或覆盖项目内文件。"""

    def __init__(self, project_root: Path):
        self._root = project_root
        meta = SkillMetadata(
            skill_id="win11_write_file",
            name="Win11 写文件",
            description="在项目工作区内创建或覆盖文本文件；可自动创建父目录。",
            category=SkillCategory.TOOL,
            subcategory="file",
            input_schema={
                "type": "object",
                "required": ["path", "content"],
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string", "description": "文件完整内容"},
                    "encoding": {"type": "string", "default": "utf-8"},
                    "create_parent_dirs": {
                        "type": "boolean",
                        "default": True,
                        "description": "是否创建缺失的父目录",
                    },
                },
            },
            estimated_time=2,
            complexity=SkillComplexity.SIMPLE,
            provides_skills=["project_fs_write"],
        )
        super().__init__(meta)

    def execute(self, **kwargs) -> dict:
        path = kwargs.get("path", "")
        content = kwargs.get("content")
        if content is None:
            return _fail("content 不能为空")
        encoding = (kwargs.get("encoding") or "utf-8").strip() or "utf-8"
        create_parents = bool(kwargs.get("create_parent_dirs", True))

        data = content if isinstance(content, str) else str(content)
        raw_bytes = data.encode(encoding, errors="strict")
        if len(raw_bytes) > _DEFAULT_MAX_WRITE:
            return _fail(f"内容超过最大写入限制（{_DEFAULT_MAX_WRITE} 字节）")

        ok, err, resolved = resolve_project_path(self._root, str(path))
        if not ok or resolved is None:
            return _fail(err)
        try:
            if create_parents:
                resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_bytes(raw_bytes)
        except OSError as e:
            _LOG.warning("[win11_write_file] %s", e)
            return _fail(str(e))
        return {"observation": f"已写入 {resolved}（{len(raw_bytes)} 字节）", "bytes_written": len(raw_bytes)}


class Win11DeleteFileSkill(AtomicSkill):
    """删除项目内文件或目录。"""

    def __init__(self, project_root: Path):
        self._root = project_root
        meta = SkillMetadata(
            skill_id="win11_delete_file",
            name="Win11 删文件",
            description="删除项目工作区内的文件；删除目录需 recursive=true（有条目数上限以防误删巨树）。",
            category=SkillCategory.TOOL,
            subcategory="file",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "recursive": {
                        "type": "boolean",
                        "default": False,
                        "description": "删除目录时是否递归删除内容",
                    },
                },
            },
            estimated_time=2,
            complexity=SkillComplexity.SIMPLE,
            provides_skills=["project_fs_delete"],
        )
        super().__init__(meta)

    def execute(self, **kwargs) -> dict:
        path = kwargs.get("path", "")
        recursive = bool(kwargs.get("recursive", False))

        ok, err, resolved = resolve_project_path(self._root, str(path))
        if not ok or resolved is None:
            return _fail(err)
        if not resolved.exists():
            return _fail("路径不存在")
        try:
            if resolved.is_file():
                resolved.unlink()
                return {"observation": f"已删除文件 {resolved.name}"}
            if resolved.is_dir():
                if not recursive:
                    try:
                        resolved.rmdir()
                        return {"observation": f"已删除空目录 {resolved.name}"}
                    except OSError:
                        return _fail("目录非空：请设置 recursive=true 以递归删除")
                cnt = _count_walk_entries(resolved)
                if cnt > _MAX_RMDIR_ENTRIES:
                    return _fail(
                        f"目录条目超过上限 {_MAX_RMDIR_ENTRIES}（约 {cnt}），"
                        "拒绝递归删除以防误操作"
                    )
                shutil.rmtree(resolved)
                return {"observation": f"已递归删除目录 {resolved.name}"}
            return _fail("未知路径类型")
        except OSError as e:
            _LOG.warning("[win11_delete_file] %s", e)
            return _fail(str(e))


class Win11ModifyFileSkill(AtomicSkill):
    """在项目内文本文件中查找并替换。"""

    def __init__(self, project_root: Path):
        self._root = project_root
        meta = SkillMetadata(
            skill_id="win11_modify_file",
            name="Win11 改文件",
            description="在项目工作区内对文本文件做查找替换；replace_all 控制替换一处或全部。",
            category=SkillCategory.TOOL,
            subcategory="file",
            input_schema={
                "type": "object",
                "required": ["path", "find", "replace"],
                "properties": {
                    "path": {"type": "string"},
                    "find": {"type": "string", "description": "查找子串（不可为空）"},
                    "replace": {"type": "string", "description": "替换为（可为空表示删除匹配）"},
                    "replace_all": {"type": "boolean", "default": False},
                    "encoding": {"type": "string", "default": "utf-8"},
                },
            },
            estimated_time=3,
            complexity=SkillComplexity.SIMPLE,
            provides_skills=["project_fs_modify"],
        )
        super().__init__(meta)

    def execute(self, **kwargs) -> dict:
        path = kwargs.get("path", "")
        find = kwargs.get("find")
        replace = kwargs.get("replace")
        if find is None or str(find) == "":
            return _fail("find 不能为空")
        if replace is None:
            replace = ""
        find_s = str(find)
        rep_s = str(replace) if isinstance(replace, str) else str(replace)
        replace_all = bool(kwargs.get("replace_all", False))
        encoding = (kwargs.get("encoding") or "utf-8").strip() or "utf-8"

        ok, err, resolved = resolve_project_path(self._root, str(path))
        if not ok or resolved is None:
            return _fail(err)
        if not resolved.is_file():
            return _fail("路径不是文件")
        if resolved.stat().st_size > _DEFAULT_MAX_WRITE:
            return _fail("文件过大，拒绝整文件替换")
        try:
            text = resolved.read_text(encoding=encoding, errors="strict")
        except UnicodeDecodeError:
            return _fail("非文本文件或编码不匹配，请换 encoding 或勿对二进制使用本工具")
        except OSError as e:
            return _fail(str(e))

        if replace_all:
            count = text.count(find_s)
            new_text = text.replace(find_s, rep_s) if count else text
        else:
            idx = text.find(find_s)
            if idx < 0:
                count = 0
                new_text = text
            else:
                count = 1
                new_text = text[:idx] + rep_s + text[idx + len(find_s) :]
        if count == 0:
            return {
                "replacements": 0,
                "observation": "未找到匹配子串，文件未修改",
            }
        try:
            resolved.write_text(new_text, encoding=encoding)
        except OSError as e:
            return _fail(str(e))
        return {
            "replacements": count,
            "observation": f"已替换 {count} 处，已写回 {resolved.name}",
        }


class Win11MoveFileSkill(AtomicSkill):
    """在项目工作区内移动或重命名文件/目录。"""

    def __init__(self, project_root: Path):
        self._root = project_root
        meta = SkillMetadata(
            skill_id="win11_move_file",
            name="Win11 移动/重命名",
            description="在项目工作区内移动或重命名；source 与 destination 均须在项目根下。",
            category=SkillCategory.TOOL,
            subcategory="file",
            input_schema={
                "type": "object",
                "required": ["source", "destination"],
                "properties": {
                    "source": {"type": "string"},
                    "destination": {"type": "string"},
                    "overwrite": {"type": "boolean", "default": False},
                },
            },
            estimated_time=2,
            complexity=SkillComplexity.SIMPLE,
            provides_skills=["project_fs_move"],
        )
        super().__init__(meta)

    def execute(self, **kwargs) -> dict:
        src = kwargs.get("source") or kwargs.get("src")
        dst = kwargs.get("destination") or kwargs.get("dest")
        overwrite = bool(kwargs.get("overwrite", False))

        if not src or not dst:
            return _fail("source 与 destination 均不能为空")

        ok_s, err_s, res_src = resolve_project_path(self._root, str(src))
        if not ok_s or res_src is None:
            return _fail(f"source 无效: {err_s}")
        ok_d, err_d, res_dst = resolve_project_path(self._root, str(dst))
        if not ok_d or res_dst is None:
            return _fail(f"destination 无效: {err_d}")

        if not res_src.exists():
            return _fail("源路径不存在")
        if res_dst.exists() and not overwrite:
            return _fail("目标已存在：设置 overwrite=true 覆盖")

        try:
            res_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(res_src), str(res_dst))
        except OSError as e:
            _LOG.warning("[win11_move_file] %s", e)
            return _fail(str(e))
        return {"observation": f"已移动至 {res_dst}"}


def create_win11_project_fs_skill_bundle(project_folder: str) -> dict[str, AtomicSkill]:
    """
    构造并返回 5 个技能实例的字典，供 ``skills_registry.update(...)`` 使用。

    Args:
        project_folder: 项目工作区根目录（与 file_access 相同）
    """
    root = Path(project_folder)
    return {
        "win11_read_file": Win11ReadFileSkill(root),
        "win11_write_file": Win11WriteFileSkill(root),
        "win11_delete_file": Win11DeleteFileSkill(root),
        "win11_modify_file": Win11ModifyFileSkill(root),
        "win11_move_file": Win11MoveFileSkill(root),
    }
