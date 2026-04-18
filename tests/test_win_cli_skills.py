"""Windows CLI 技能：校验逻辑与 MCP 输出（跨平台）；真机子进程仅 Windows。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from uap.core.action.react.win_cli_skills import (
    RunAllowedWinCmdSkill,
    RunAllowedWinPowerShellSkill,
    RunSafeWinCmdSkill,
    RunSafeWinPowerShellSkill,
    _has_forbidden_shell_ops,
    _load_allowed_cmd_json,
    _mcp_text_observation,
    _validate_allowed_powershell,
    _validate_allowed_win_cmd,
    _validate_safe_powershell,
    _validate_safe_win_cmd,
    create_win_cli_skill_bundle,
)
from uap.config import ContextCompressionConfig
from uap.react.dst_manager import DstManager
from uap.react.react_agent import ReactAgent


def test_forbidden_shell_ops() -> None:
    assert not _has_forbidden_shell_ops("dir")
    assert _has_forbidden_shell_ops("a|b")
    assert _has_forbidden_shell_ops("a>b")
    assert _has_forbidden_shell_ops("a&b")


def test_safe_win_cmd_whitelist() -> None:
    ok, _ = _validate_safe_win_cmd("dir")
    assert ok
    ok, _ = _validate_safe_win_cmd("date /t")
    assert ok
    ok, msg = _validate_safe_win_cmd("date")
    assert not ok
    ok, _ = _validate_safe_win_cmd("echo hi")
    assert ok
    ok, msg = _validate_safe_win_cmd("format c:")
    assert not ok


def test_allowed_win_cmd_normalized_match() -> None:
    allowed = ["dir /b", "ver"]
    ok, _ = _validate_allowed_win_cmd("dir /b", allowed)
    assert ok
    ok, _ = _validate_allowed_win_cmd("  dir   /b  ", allowed)
    assert ok
    ok, msg = _validate_allowed_win_cmd("dir", allowed)
    assert not ok


def test_safe_powershell_subset() -> None:
    ok, _ = _validate_safe_powershell("Get-ChildItem")
    assert ok
    ok, _ = _validate_safe_powershell("Get-ChildItem | Select-Object Name")
    assert not ok  # 通用禁符含 |
    ok, msg = _validate_safe_powershell("Remove-Item x")
    assert not ok
    ok, msg = _validate_safe_powershell("{ 1 }")
    assert not ok
    ok, msg = _validate_safe_powershell("-EncodedCommand xxx")
    assert not ok


def test_allowed_powershell_whitelist_and_uri() -> None:
    al = ["New-Item", "Get-ChildItem"]
    ok, _ = _validate_allowed_powershell("Get-ChildItem", al)
    assert ok
    ok, msg = _validate_allowed_powershell("Invoke-Expression '1'", al)
    assert not ok
    ok, msg = _validate_allowed_powershell(
        "New-Item -Uri http://example.com/foo", al
    )
    assert not ok
    ok, _ = _validate_allowed_powershell(
        "New-Item -Uri http://127.0.0.1/foo", al
    )
    assert ok


def test_mcp_text_json_roundtrip() -> None:
    s = _mcp_text_observation(
        exit_code=0,
        cwd="C:\\proj",
        label="t",
        stdout="hi",
        stderr="",
    )
    d = json.loads(s)
    assert d["type"] == "text"
    assert "hi" in d["text"]


def test_load_allowed_cmd_json(tmp_path: Path) -> None:
    cfg = tmp_path / "allowed_cmd.json"
    cfg.write_text('{"allowed":["ver"]}', encoding="utf-8")
    got, err = _load_allowed_cmd_json(cfg)
    assert err is None
    assert got == ["ver"]


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only")
def test_bundle_echo_smoke(tmp_path: Path) -> None:
    bundle = create_win_cli_skill_bundle(str(tmp_path))
    skill = bundle["run_safe_win_cmd"]
    out = skill.execute(command="echo smoke", project_workspace=str(tmp_path))
    assert "observation" in out
    assert out.get("is_error") is False
    payload = json.loads(out["observation"])
    assert payload["type"] == "text"
    assert "smoke" in payload["text"]


def test_react_execute_skill_preserves_observation_on_is_error() -> None:
    m = MagicMock()
    m.bind_tools = lambda *a, **k: m
    dst = DstManager()
    agent = ReactAgent(
        chat_model=m,
        skills_registry={},
        dst_manager=dst,
        max_iterations=2,
        max_time_seconds=30.0,
        max_ask_user_per_turn=1,
        compression_config=ContextCompressionConfig(enabled=False),
    )

    class _Sk:
        metadata = MagicMock()
        metadata.requires_confirmation = False

        def validate_input(self, **kwargs):
            return True, []

        def execute(self, **kwargs):
            return {
                "observation": "BODY",
                "is_error": True,
                "error_message": "exit 1",
            }

    agent.skills["t"] = _Sk()
    obs, is_err, em = agent._execute_skill("t", {})
    assert obs == "BODY"
    assert is_err is True
    assert em == "exit 1"


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="cmd.exe path")
@patch("uap.core.action.react.win_cli_skills.subprocess.run")
def test_run_subprocess_timeout_mcp(mock_run: MagicMock, tmp_path: Path) -> None:
    import subprocess as sp

    mock_run.side_effect = sp.TimeoutExpired(cmd="x", timeout=1)
    skill = RunSafeWinCmdSkill(tmp_path)
    out = skill.execute(command="echo hi", project_workspace=str(tmp_path))
    assert out["is_error"] is True
    pl = json.loads(out["observation"])
    assert "超时" in pl["text"]


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows CLI skills")
def test_allowed_cmd_skill_missing_config(tmp_path: Path) -> None:
    skill = RunAllowedWinCmdSkill(tmp_path)
    out = skill.execute(command="ver", project_workspace=str(tmp_path))
    assert out["is_error"] is True
    assert "未找到配置" in json.loads(out["observation"]).get("text", "")
