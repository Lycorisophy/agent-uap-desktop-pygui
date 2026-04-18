"""
Windows 项目工作区内受限 CLI / PowerShell 执行（run_safe_* / run_allowed_*）。

- 使用 ``subprocess`` 且 ``shell=False``；``cmd.exe /c`` 与 ``powershell.exe -NoProfile -NonInteractive -Command``。
- 输出截断、超时与 MCP ``TextContent`` 形态见 ``_execute_cli``。
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from uap.skill.atomic_skills import AtomicSkill, SkillCategory, SkillComplexity, SkillMetadata

_LOG = logging.getLogger("uap.core.action.react.win_cli")

CLI_TIMEOUT_SEC = 30
OUTPUT_MAX_BYTES = 10 * 1024

_FORBIDDEN_CMD_CHARS = frozenset("|><&^")

_SAFE_CMD_FIRST = frozenset(
    {
        "dir",
        "type",
        "cd",
        "echo",
        "findstr",
        "where",
        "ver",
        "tree",
        "more",
    }
)

_PS_SAFE_EXTRA = frozenset(
    {
        "Select-Object",
        "Where-Object",
        "Sort-Object",
        "Format-Table",
        "Format-List",
        "Out-String",
        "Measure-Object",
        "Compare-Object",
        "Group-Object",
        "Tee-Object",
    }
)

def _windows_system32_exe(name: str) -> Path:
    root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return (root / "System32" / name).resolve()


def _powershell_exe() -> Path:
    root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    p = root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return p.resolve()


def _has_forbidden_shell_ops(s: str) -> bool:
    return any(c in s for c in _FORBIDDEN_CMD_CHARS)


def _normalize_cmd_line(s: str) -> str:
    return " ".join((s or "").split())


def _truncate_output(s: str, max_len: int = OUTPUT_MAX_BYTES) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _mcp_text_observation(
    *,
    exit_code: int,
    cwd: str,
    label: str,
    stdout: str,
    stderr: str,
) -> str:
    body_lines = [
        f"[{label}] exit_code={exit_code}",
        f"cwd={cwd}",
        "--- stdout ---",
        stdout or "(empty)",
        "--- stderr ---",
        stderr or "(empty)",
    ]
    body = "\n".join(body_lines)
    body = _truncate_output(body, OUTPUT_MAX_BYTES)
    payload = {"type": "text", "text": body}
    return json.dumps(payload, ensure_ascii=False)


def _skill_result(
    *,
    exit_code: int,
    cwd: str,
    label: str,
    stdout: str,
    stderr: str,
    error_message: str | None = None,
) -> dict[str, Any]:
    obs = _mcp_text_observation(
        exit_code=exit_code,
        cwd=cwd,
        label=label,
        stdout=stdout,
        stderr=stderr,
    )
    err = exit_code != 0
    out: dict[str, Any] = {
        "observation": obs,
        "is_error": err,
    }
    if err:
        out["error_message"] = error_message or f"进程退出码 {exit_code}"
    return out


def _resolve_workspace(kwargs: dict[str, Any], root: Path) -> tuple[bool, str, Path | None]:
    ws = (kwargs.get("project_workspace") or kwargs.get("workspace_root") or "").strip()
    if not ws:
        return False, "缺少 project_workspace", None
    try:
        p = Path(ws).expanduser().resolve()
    except OSError as e:
        return False, f"工作目录无效: {e}", None
    if not p.is_dir():
        return False, "project_workspace 不是目录", None
    try:
        p.relative_to(root.resolve())
    except ValueError:
        return False, "工作目录必须在项目根目录之下", None
    return True, "", p


def _validate_safe_win_cmd(command: str) -> tuple[bool, str]:
    s = (command or "").strip()
    if not s:
        return False, "命令不能为空"
    if _has_forbidden_shell_ops(s):
        return False, "禁止使用的 shell 字符: | > < & ^"
    parts = s.split()
    if not parts:
        return False, "命令不能为空"
    low0 = parts[0].lower()
    if low0 in ("date", "time"):
        if len(parts) >= 2 and parts[1].lower() == "/t":
            return True, ""
        return False, "仅允许 date /t 与 time /t"
    if low0 not in _SAFE_CMD_FIRST:
        return False, f"命令不在只读白名单内: {low0!r}"
    return True, ""


def _load_allowed_cmd_json(config_path: Path) -> tuple[list[str] | None, str | None]:
    if not config_path.is_file():
        return None, f"未找到配置文件: {config_path}"
    try:
        raw = config_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        return None, f"读取或解析失败: {e}"
    allowed = data.get("allowed") if isinstance(data, dict) else None
    if not isinstance(allowed, list):
        return None, "JSON 须包含 allowed 数组"
    out: list[str] = []
    for x in allowed:
        if isinstance(x, str) and x.strip():
            out.append(_normalize_cmd_line(x))
    if not out:
        return None, "allowed 为空"
    return out, None


def _validate_allowed_win_cmd(command: str, allowed_lines: list[str]) -> tuple[bool, str]:
    s = (command or "").strip()
    if not s:
        return False, "命令不能为空"
    if _has_forbidden_shell_ops(s):
        return False, "禁止使用的 shell 字符: | > < & ^"
    norm = _normalize_cmd_line(s)
    if norm not in allowed_lines:
        return False, "命令不在项目 allowed_cmd.json 白名单内"
    return True, ""


CMDLET_RE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9]*-[A-Za-z][A-Za-z0-9_]*)\b",
    re.ASCII,
)


def _extract_cmdlets(script: str) -> list[str]:
    return list(dict.fromkeys(CMDLET_RE.findall(script or "")))


def _ps_cmdlet_allowed_in_safe_mode(name: str) -> bool:
    """只读安全模式：仅 ``Get-*`` 与固定列表中的 cmdlet。"""
    if name.startswith("Get-"):
        return True
    if name in _PS_SAFE_EXTRA:
        return True
    return False


def _validate_safe_powershell(script: str) -> tuple[bool, str]:
    s = (script or "").strip()
    if not s:
        return False, "脚本不能为空"
    if _has_forbidden_shell_ops(s):
        return False, "禁止使用的字符: | > < & ^"
    if "{" in s or "}" in s:
        return False, "禁止脚本块 { }"
    low = s.lower()
    if "-encodedcommand" in low or re.search(r"\s-enc\b", low):
        return False, "禁止使用 -EncodedCommand / -enc"
    for cm in _extract_cmdlets(s):
        if not _ps_cmdlet_allowed_in_safe_mode(cm):
            return False, f"cmdlet 不在只读安全子集: {cm}"
    return True, ""


def _load_allowed_ps_json(config_path: Path) -> tuple[list[str] | None, str | None]:
    if not config_path.is_file():
        return None, f"未找到配置文件: {config_path}"
    try:
        raw = config_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        return None, f"读取或解析失败: {e}"
    allowed = data.get("allowed") if isinstance(data, dict) else None
    if not isinstance(allowed, list):
        return None, "JSON 须包含 allowed 数组"
    out: list[str] = []
    for x in allowed:
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
    if not out:
        return None, "allowed 为空"
    return out, None


def _uri_target_host(value: str) -> str:
    v = value.strip().strip('"').strip("'")
    if "://" in v:
        u = urlparse(v)
        return (u.hostname or "").strip()
    # path or host:port
    part = v.split("/")[0]
    if ":" in part and not part.startswith("["):
        host, _, _ = part.rpartition(":")
        if host:
            return host.strip("[]")
    return part.strip("[]")


def _host_is_local_or_private(host: str) -> bool:
    h = (host or "").strip().lower()
    if not h:
        return False
    if h == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(h)
        return bool(ip.is_private or ip.is_loopback or ip.is_link_local)
    except ValueError:
        return False


def _validate_uri_params_allowed(script: str) -> tuple[bool, str]:
    """任意 ``-Uri`` 须指向 localhost 或私网/环回（可配置白名单模式下的额外约束）。"""
    for m in re.finditer(
        r"-Uri\s+([^\s]+|'[^']*'|\"[^\"]*\")",
        script,
        flags=re.IGNORECASE,
    ):
        raw_val = m.group(1)
        host = _uri_target_host(raw_val)
        if not _host_is_local_or_private(host):
            return False, f"-Uri 目标不在允许范围（须 localhost 或内网）: {host!r}"
    return True, ""


def _validate_allowed_powershell(
    script: str, allowed_list: list[str]
) -> tuple[bool, str]:
    s = (script or "").strip()
    if not s:
        return False, "脚本不能为空"
    if _has_forbidden_shell_ops(s):
        return False, "禁止使用的字符: | > < & ^"
    if "{" in s or "}" in s:
        return False, "禁止脚本块 { }"
    low = s.lower()
    if "-encodedcommand" in low or re.search(r"\s-enc\b", low):
        return False, "禁止使用 -EncodedCommand / -enc"
    allowed_set = frozenset(allowed_list)
    for cm in _extract_cmdlets(s):
        if cm.startswith("Get-"):
            continue
        if cm not in allowed_set:
            return False, f"cmdlet 不在白名单: {cm}"
    ok_uri, msg_uri = _validate_uri_params_allowed(s)
    if not ok_uri:
        return False, msg_uri
    return True, ""


def _run_subprocess(
    argv: list[str],
    cwd: Path,
    *,
    label: str,
) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CLI_TIMEOUT_SEC,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return _skill_result(
            exit_code=-1,
            cwd=str(cwd),
            label=label,
            stdout="",
            stderr=f"超时（>{CLI_TIMEOUT_SEC}s）",
            error_message="timeout",
        )
    except OSError as e:
        return {
            "observation": json.dumps(
                {"type": "text", "text": f"执行失败: {e}"},
                ensure_ascii=False,
            ),
            "is_error": True,
            "error_message": str(e),
        }
    out = (proc.stdout or "")[:OUTPUT_MAX_BYTES]
    err = (proc.stderr or "")[:OUTPUT_MAX_BYTES]
    return _skill_result(
        exit_code=int(proc.returncode),
        cwd=str(cwd),
        label=label,
        stdout=out,
        stderr=err,
    )


class RunSafeWinCmdSkill(AtomicSkill):
    """``cmd.exe /c`` 只读白名单。"""

    def __init__(self, project_root: Path):
        self._root = project_root
        meta = SkillMetadata(
            skill_id="run_safe_win_cmd",
            name="安全 CMD（只读白名单）",
            description=(
                "仅 Windows。在项目工作区内以 cmd.exe /c 执行只读命令（dir/type/cd/echo 等硬编码白名单）。"
                "禁止 | > < & ^。输出为 MCP TextContent JSON（observation）。"
            ),
            category=SkillCategory.TOOL,
            subcategory="cli",
            input_schema={
                "type": "object",
                "required": ["command"],
                "properties": {
                    "command": {"type": "string", "description": "单行 cmd 命令（无管道与重定向）"},
                },
            },
            estimated_time=5,
            complexity=SkillComplexity.MODERATE,
        )
        super().__init__(meta)

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        if sys.platform != "win32":
            return {
                "observation": json.dumps(
                    {"type": "text", "text": "仅支持 Windows"},
                    ensure_ascii=False,
                ),
                "is_error": True,
                "error_message": "not_windows",
            }
        cmd = str(kwargs.get("command") or "").strip()
        ok, msg = _validate_safe_win_cmd(cmd)
        if not ok:
            return {
                "observation": json.dumps({"type": "text", "text": msg}, ensure_ascii=False),
                "is_error": True,
                "error_message": msg,
            }
        wok, wmsg, cwd = _resolve_workspace(kwargs, self._root)
        if not wok or cwd is None:
            return {
                "observation": json.dumps({"type": "text", "text": wmsg}, ensure_ascii=False),
                "is_error": True,
                "error_message": wmsg,
            }
        exe = _windows_system32_exe("cmd.exe")
        return _run_subprocess([str(exe), "/c", cmd], cwd, label="run_safe_win_cmd")


class RunAllowedWinCmdSkill(AtomicSkill):
    """``cmd.exe /c`` 项目配置白名单。"""

    def __init__(self, project_root: Path):
        self._root = project_root
        meta = SkillMetadata(
            skill_id="run_allowed_win_cmd",
            name="可配置 CMD",
            description=(
                "仅 Windows。读取项目 config/allowed_cmd.json 中的命令白名单后执行 cmd.exe /c。"
                "禁止 | > < & ^。"
            ),
            category=SkillCategory.TOOL,
            subcategory="cli",
            input_schema={
                "type": "object",
                "required": ["command"],
                "properties": {
                    "command": {"type": "string", "description": "须与白名单条目一致（规范化空白后匹配）"},
                },
            },
            estimated_time=5,
            complexity=SkillComplexity.MODERATE,
        )
        super().__init__(meta)

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        if sys.platform != "win32":
            return {
                "observation": json.dumps(
                    {"type": "text", "text": "仅支持 Windows"},
                    ensure_ascii=False,
                ),
                "is_error": True,
                "error_message": "not_windows",
            }
        cfg = self._root / "config" / "allowed_cmd.json"
        allowed, err = _load_allowed_cmd_json(cfg)
        if allowed is None:
            return {
                "observation": json.dumps({"type": "text", "text": err or "配置错误"}, ensure_ascii=False),
                "is_error": True,
                "error_message": err or "config",
            }
        cmd = str(kwargs.get("command") or "").strip()
        ok, msg = _validate_allowed_win_cmd(cmd, allowed)
        if not ok:
            return {
                "observation": json.dumps({"type": "text", "text": msg}, ensure_ascii=False),
                "is_error": True,
                "error_message": msg,
            }
        wok, wmsg, cwd = _resolve_workspace(kwargs, self._root)
        if not wok or cwd is None:
            return {
                "observation": json.dumps({"type": "text", "text": wmsg}, ensure_ascii=False),
                "is_error": True,
                "error_message": wmsg,
            }
        exe = _windows_system32_exe("cmd.exe")
        return _run_subprocess([str(exe), "/c", cmd], cwd, label="run_allowed_win_cmd")


class RunSafeWinPowerShellSkill(AtomicSkill):
    """PowerShell 只读安全子集。"""

    def __init__(self, project_root: Path):
        self._root = project_root
        meta = SkillMetadata(
            skill_id="run_safe_win_powershell",
            name="安全 PowerShell（只读）",
            description=(
                "仅 Windows。powershell -NoProfile -NonInteractive -Command。"
                "允许 Get-* 及 Select/Where/Sort/Format/Out-String 等；禁止 Set/Invoke/Remove 等前缀与脚本块。"
            ),
            category=SkillCategory.TOOL,
            subcategory="cli",
            input_schema={
                "type": "object",
                "required": ["script"],
                "properties": {
                    "script": {"type": "string", "description": "单行或简短 PowerShell，勿用管道连接 shell 重定向"},
                },
            },
            estimated_time=5,
            complexity=SkillComplexity.MODERATE,
        )
        super().__init__(meta)

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        if sys.platform != "win32":
            return {
                "observation": json.dumps(
                    {"type": "text", "text": "仅支持 Windows"},
                    ensure_ascii=False,
                ),
                "is_error": True,
                "error_message": "not_windows",
            }
        script = str(kwargs.get("script") or "").strip()
        ok, msg = _validate_safe_powershell(script)
        if not ok:
            return {
                "observation": json.dumps({"type": "text", "text": msg}, ensure_ascii=False),
                "is_error": True,
                "error_message": msg,
            }
        wok, wmsg, cwd = _resolve_workspace(kwargs, self._root)
        if not wok or cwd is None:
            return {
                "observation": json.dumps({"type": "text", "text": wmsg}, ensure_ascii=False),
                "is_error": True,
                "error_message": wmsg,
            }
        exe = _powershell_exe()
        return _run_subprocess(
            [str(exe), "-NoProfile", "-NonInteractive", "-Command", script],
            cwd,
            label="run_safe_win_powershell",
        )


class RunAllowedWinPowerShellSkill(AtomicSkill):
    """PowerShell 可配置 cmdlet 白名单。"""

    def __init__(self, project_root: Path):
        self._root = project_root
        meta = SkillMetadata(
            skill_id="run_allowed_win_powershell",
            name="可配置 PowerShell",
            description=(
                "仅 Windows。读取 config/allowed_ps_cmdlets.json。"
                "白名单外 cmdlet 拒绝；写类 cmdlet 若含 -Uri 须指向 localhost 或内网。"
            ),
            category=SkillCategory.TOOL,
            subcategory="cli",
            input_schema={
                "type": "object",
                "required": ["script"],
                "properties": {
                    "script": {"type": "string", "description": "PowerShell 命令或管道脚本"},
                },
            },
            estimated_time=5,
            complexity=SkillComplexity.MODERATE,
        )
        super().__init__(meta)

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        if sys.platform != "win32":
            return {
                "observation": json.dumps(
                    {"type": "text", "text": "仅支持 Windows"},
                    ensure_ascii=False,
                ),
                "is_error": True,
                "error_message": "not_windows",
            }
        cfg = self._root / "config" / "allowed_ps_cmdlets.json"
        allowed, err = _load_allowed_ps_json(cfg)
        if allowed is None:
            return {
                "observation": json.dumps({"type": "text", "text": err or "配置错误"}, ensure_ascii=False),
                "is_error": True,
                "error_message": err or "config",
            }
        script = str(kwargs.get("script") or "").strip()
        ok, msg = _validate_allowed_powershell(script, allowed)
        if not ok:
            return {
                "observation": json.dumps({"type": "text", "text": msg}, ensure_ascii=False),
                "is_error": True,
                "error_message": msg,
            }
        wok, wmsg, cwd = _resolve_workspace(kwargs, self._root)
        if not wok or cwd is None:
            return {
                "observation": json.dumps({"type": "text", "text": wmsg}, ensure_ascii=False),
                "is_error": True,
                "error_message": wmsg,
            }
        exe = _powershell_exe()
        return _run_subprocess(
            [str(exe), "-NoProfile", "-NonInteractive", "-Command", script],
            cwd,
            label="run_allowed_win_powershell",
        )


def create_win_cli_skill_bundle(project_folder: str) -> dict[str, AtomicSkill]:
    """
    构造四个 Windows CLI 技能，供 ``skills_registry.update(...)`` 使用。

    Args:
        project_folder: 项目根目录（与 file_access / win11_* 一致）
    """
    root = Path(project_folder)
    return {
        "run_safe_win_cmd": RunSafeWinCmdSkill(root),
        "run_allowed_win_cmd": RunAllowedWinCmdSkill(root),
        "run_safe_win_powershell": RunSafeWinPowerShellSkill(root),
        "run_allowed_win_powershell": RunAllowedWinPowerShellSkill(root),
    }
