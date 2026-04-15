"""本机文件夹浏览与打开。"""

from __future__ import annotations

import os
import subprocess
import sys

from uap.infrastructure.persistence.project_store import user_workspace_dir

from uap.interfaces.api._log import _LOG


class FilesystemApiMixin:
    def get_project_folder(self, project_id: str) -> dict:
        """返回用户「项目空间」目录（~/.uap/workspace/{id}），必要时回退到元数据目录。"""
        try:
            project = self.project_store.get_project(project_id)
            if not project:
                return {"success": False, "error": "项目不存在"}
            folder_path = (project.folder_path or project.workspace or "").strip()
            if not folder_path or not os.path.isdir(folder_path):
                uws = str(user_workspace_dir(project_id))
                if os.path.isdir(uws):
                    folder_path = uws
                else:
                    folder_path = str(self.project_store.resolve_project_directory(project_id))
            return {
                "success": True,
                "folder_path": folder_path,
                "project_name": project.name,
            }
        except Exception as e:
            _LOG.error("获取项目文件夹失败: %s", e)
            return {"success": False, "error": str(e)}

    def open_folder(self, folder_path: str) -> dict:
        """在系统文件管理器中打开文件夹。"""
        try:
            if not os.path.exists(folder_path):
                return {"success": False, "error": "文件夹不存在"}

            if sys.platform == "win32":
                os.startfile(folder_path)
            elif sys.platform == "darwin":
                subprocess.run(["open", folder_path], check=False)
            else:
                subprocess.run(["xdg-open", folder_path], check=False)

            return {"success": True}
        except Exception as e:
            _LOG.error("打开文件夹失败: %s", e)
            return {"success": False, "error": str(e)}

    def list_directory(self, folder_path: str) -> dict:
        """列出目录内容。"""
        try:
            if not os.path.exists(folder_path):
                return {"success": False, "error": "文件夹不存在", "files": []}

            files = []
            for item in os.listdir(folder_path):
                item_path = os.path.join(folder_path, item)
                is_dir = os.path.isdir(item_path)
                size = 0 if is_dir else os.path.getsize(item_path)
                files.append(
                    {
                        "name": item,
                        "path": item_path,
                        "is_directory": is_dir,
                        "size": size,
                    }
                )

            files.sort(key=lambda x: (not x["is_directory"], x["name"].lower()))

            return {"success": True, "files": files}
        except Exception as e:
            _LOG.error("列出目录失败: %s", e)
            return {"success": False, "error": str(e), "files": []}
