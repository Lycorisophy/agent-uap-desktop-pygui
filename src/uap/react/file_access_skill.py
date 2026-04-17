"""
UAP 文件访问技能

让ReAct Agent能够访问项目文件夹中的文件。
支持项目内文件读取和列表操作。
"""

from __future__ import annotations

import os
import logging
from typing import Any, Optional, List
from pathlib import Path

from uap.react.project_path_utils import normalize_relative_path_for_project
from uap.skill.atomic_skills import AtomicSkill, SkillMetadata, SkillCategory, SkillComplexity

_LOG = logging.getLogger("uap.react.file_access")


class FileAccessSkill(AtomicSkill):
    """项目文件访问技能"""

    def __init__(
        self,
        project_folder: Optional[str] = None,
        read_file_func: Optional[callable] = None,
        list_dir_func: Optional[callable] = None,
        auth_callback: Optional[callable] = None
    ):
        """
        初始化文件访问技能

        Args:
            project_folder: 项目根目录
            read_file_func: 读取文件函数，签名为 (path: str) -> str
            list_dir_func: 列出目录函数，签名为 (path: str) -> list[dict]
            auth_callback: 授权回调函数，用于请求非项目文件访问授权
        """
        metadata = SkillMetadata(
            skill_id="file_access",
            name="项目文件访问",
            description="读取项目文件夹中的文件内容、列出目录结构。智能体原生能力，已授权。",
            category=SkillCategory.TOOL,
            subcategory="file",
            input_schema={
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read", "list", "exists"],
                        "description": "操作类型：read读取文件，list列出目录，exists检查文件是否存在"
                    },
                    "path": {
                        "type": "string",
                        "description": "文件或目录的相对路径（相对于项目根目录）或绝对路径"
                    },
                    "encoding": {
                        "type": "string",
                        "default": "utf-8",
                        "description": "文件编码"
                    },
                    "max_size": {
                        "type": "integer",
                        "default": 1024 * 1024,
                        "description": "最大读取文件大小（字节）"
                    }
                }
            },
            output_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "文件内容（读取操作）"},
                    "files": {"type": "array", "description": "文件列表（列出操作）"},
                    "exists": {"type": "boolean", "description": "文件是否存在（检查操作）"},
                    "error": {"type": "string", "description": "错误信息"}
                }
            },
            estimated_time=2,
            complexity=SkillComplexity.SIMPLE,
            provides_skills=["file_reading", "directory_listing"]
        )
        super().__init__(metadata)
        self._project_folder = project_folder
        self._read_file_func = read_file_func
        self._list_dir_func = list_dir_func
        self._auth_callback = auth_callback

    def set_project_folder(self, folder: str) -> None:
        """设置项目文件夹"""
        self._project_folder = folder

    def _is_path_safe(self, path: str) -> tuple[bool, str]:
        """
        检查路径是否安全（防止路径穿越攻击）

        Returns:
            (is_safe, resolved_path)
        """
        if not self._project_folder:
            return True, path

        try:
            # 转换为绝对路径
            if os.path.isabs(path):
                resolved = os.path.realpath(path)
            else:
                resolved = os.path.realpath(os.path.join(self._project_folder, path))

            # 确保路径在项目文件夹内
            project_real = os.path.realpath(self._project_folder)
            if not resolved.startswith(project_real):
                return False, "访问被拒绝：路径超出项目目录范围"

            return True, resolved
        except Exception as e:
            return False, f"路径解析失败：{str(e)}"

    def execute(self, **kwargs) -> dict:
        """
        执行文件访问操作

        Args:
            action: 操作类型（read/list/exists）
            path: 文件或目录路径
            encoding: 文件编码
            max_size: 最大读取大小

        Returns:
            dict: 操作结果
        """
        action = kwargs.get("action", "read")
        path = kwargs.get("path", "")
        if self._project_folder and path and not os.path.isabs(path):
            path = normalize_relative_path_for_project(path, self._project_folder)
        encoding = kwargs.get("encoding", "utf-8")
        max_size = kwargs.get("max_size", 1024 * 1024)

        if not path:
            return {
                "error": "路径不能为空",
                "observation": "文件操作失败：缺少文件路径"
            }

        # 安全检查
        is_safe, result = self._is_path_safe(path)
        if not is_safe:
            _LOG.warning("[FileAccessSkill] Unsafe path access denied: %s", path)
            return {
                "error": result,
                "observation": f"文件操作失败：{result}"
            }

        _LOG.info("[FileAccessSkill] Performing %s on: %s", action, result)

        try:
            if action == "read":
                return self._read_file(result, encoding, max_size)
            elif action == "list":
                return self._list_directory(result)
            elif action == "exists":
                return self._check_exists(result)
            else:
                return {
                    "error": f"未知操作：{action}",
                    "observation": f"不支持的操作：{action}"
                }
        except Exception as e:
            _LOG.exception("[FileAccessSkill] Operation failed: %s", str(e))
            return {
                "error": str(e),
                "observation": f"文件操作失败：{str(e)}"
            }

    def _read_file(self, path: str, encoding: str, max_size: int) -> dict:
        """读取文件内容"""
        if not os.path.exists(path):
            return {
                "error": f"文件不存在：{path}",
                "observation": f"读取失败：文件不存在"
            }

        if not os.path.isfile(path):
            return {
                "error": f"不是文件：{path}",
                "observation": f"读取失败：路径指向目录而非文件"
            }

        file_size = os.path.getsize(path)
        if file_size > max_size:
            return {
                "error": f"文件过大：{file_size}字节 > {max_size}字节",
                "observation": f"读取失败：文件超过大小限制（{max_size // 1024}KB）"
            }

        try:
            with open(path, "r", encoding=encoding) as f:
                content = f.read()

            return {
                "content": content,
                "file_size": file_size,
                "file_name": os.path.basename(path),
                "observation": f"成功读取文件 '{os.path.basename(path)}'，大小 {file_size} 字节"
            }
        except UnicodeDecodeError:
            # 尝试二进制读取并转为base64或十六进制
            try:
                with open(path, "rb") as f:
                    content = f.read().hex()[:2000]  # 限制输出
                return {
                    "content": f"[二进制文件，已转为十六进制显示前2000字符]\n{content}...",
                    "file_size": file_size,
                    "file_name": os.path.basename(path),
                    "is_binary": True,
                    "observation": f"读取二进制文件 '{os.path.basename(path)}'"
                }
            except Exception as e:
                return {
                    "error": f"文件读取失败：{str(e)}",
                    "observation": f"读取失败：无法解码文件"
                }
        except Exception as e:
            return {
                "error": f"读取失败：{str(e)}",
                "observation": f"读取失败：{str(e)}"
            }

    def _list_directory(self, path: str) -> dict:
        """列出目录内容"""
        if not os.path.exists(path):
            return {
                "error": f"目录不存在：{path}",
                "observation": f"列出失败：目录不存在"
            }

        if not os.path.isdir(path):
            return {
                "error": f"不是目录：{path}",
                "observation": f"列出失败：路径指向文件而非目录"
            }

        try:
            items = []
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                is_dir = os.path.isdir(item_path)
                size = 0 if is_dir else os.path.getsize(item_path)
                items.append({
                    "name": item,
                    "type": "directory" if is_dir else "file",
                    "size": size,
                    "path": item_path
                })

            # 排序：目录优先，按名称排序
            items.sort(key=lambda x: (not x["type"] == "directory", x["name"].lower()))

            # 生成观察结果
            dirs = [i for i in items if i["type"] == "directory"]
            files = [i for i in items if i["type"] == "file"]

            obs = f"目录 '{os.path.basename(path)}' 包含：\n"
            if dirs:
                obs += f"📁 子目录 ({len(dirs)}): {', '.join([d['name'] for d in dirs[:5]])}"
                if len(dirs) > 5:
                    obs += f" 等共{len(dirs)}个"
                obs += "\n"
            if files:
                obs += f"📄 文件 ({len(files)}): {', '.join([f['name'] for f in files[:5]])}"
                if len(files) > 5:
                    obs += f" 等共{len(files)}个"

            return {
                "files": items,
                "directories": dirs,
                "file_count": len(files),
                "directory_count": len(dirs),
                "observation": obs
            }
        except Exception as e:
            return {
                "error": f"列出失败：{str(e)}",
                "observation": f"列出失败：{str(e)}"
            }

    def _check_exists(self, path: str) -> dict:
        """检查文件/目录是否存在"""
        exists = os.path.exists(path)
        if exists:
            is_dir = os.path.isdir(path)
            return {
                "exists": True,
                "type": "directory" if is_dir else "file",
                "observation": f"路径存在：{'目录' if is_dir else '文件'} '{path}'"
            }
        else:
            return {
                "exists": False,
                "observation": f"路径不存在：{path}"
            }


class ExternalFileAccessSkill(FileAccessSkill):
    """
    外部文件访问技能（需要授权）

    用于访问项目文件夹之外的文件，需要用户授权确认。
    """

    def __init__(self, auth_callback: Optional[callable] = None, **kwargs):
        super().__init__(**kwargs)
        # 更新元数据
        self.metadata.description = "读取项目外的文件（需要用户授权）"
        self.metadata.input_schema["properties"]["path"]["description"] = \
            "文件或目录的绝对路径或相对路径"
        self._auth_callback = auth_callback
        self._pending_auth: dict[str, bool] = {}  # 缓存授权结果

    def _is_path_safe(self, path: str) -> tuple[bool, str]:
        """扩展路径检查，允许访问项目外路径但需要授权"""
        # 如果是项目内路径，直接允许
        if self._project_folder:
            project_real = os.path.realpath(self._project_folder)
            if os.path.isabs(path):
                resolved = os.path.realpath(path)
            else:
                resolved = os.path.realpath(os.path.join(self._project_folder, path))

            if resolved.startswith(project_real):
                return True, resolved

        # 项目外路径，检查授权
        try:
            resolved = os.path.realpath(path) if os.path.isabs(path) else path

            # 检查缓存的授权
            path_key = resolved.lower()
            if path_key in self._pending_auth:
                if self._pending_auth[path_key]:
                    return True, resolved
                else:
                    return False, "访问被拒绝：用户未授权"

            # 请求授权
            if self._auth_callback:
                authorized = self._auth_callback(resolved)
                self._pending_auth[path_key] = authorized
                if authorized:
                    return True, resolved
                else:
                    return False, "访问被拒绝：用户未授权"
            else:
                return False, "访问被拒绝：需要授权但未提供授权回调"

        except Exception as e:
            return False, f"路径解析失败：{str(e)}"


def create_file_access_skill(
    project_folder: Optional[str] = None,
    read_file_func: callable = None,
    list_dir_func: callable = None
) -> FileAccessSkill:
    """
    创建项目文件访问技能

    Args:
        project_folder: 项目根目录
        read_file_func: 读取文件函数
        list_dir_func: 列出目录函数

    Returns:
        FileAccessSkill实例
    """
    return FileAccessSkill(
        project_folder=project_folder,
        read_file_func=read_file_func,
        list_dir_func=list_dir_func
    )


def create_external_file_access_skill(
    auth_callback: Optional[callable] = None,
    project_folder: Optional[str] = None
) -> ExternalFileAccessSkill:
    """
    创建外部文件访问技能

    Args:
        auth_callback: 授权回调函数
        project_folder: 项目根目录（项目内路径无需授权）

    Returns:
        ExternalFileAccessSkill实例
    """
    return ExternalFileAccessSkill(
        auth_callback=auth_callback,
        project_folder=project_folder
    )
