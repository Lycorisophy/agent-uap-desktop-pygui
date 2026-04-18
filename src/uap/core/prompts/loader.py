"""从包内 ``assets`` 或用户目录 ``~/.uap/prompts`` 加载提示词模板。"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from string import Formatter
from typing import Any

from uap.core.prompts.ids import PromptId

_USER_DIR = Path.home() / ".uap" / "prompts"
_ASSETS = "assets"


def _asset_name(prompt_id: PromptId) -> str:
    return f"{prompt_id.value}.md"


def load_raw(prompt_id: PromptId) -> str:
    """加载原始文本（无 ``str.format`` 占位符的模板须用本函数）。"""
    name = _asset_name(prompt_id)
    user_path = _USER_DIR / name
    if user_path.is_file():
        return user_path.read_text(encoding="utf-8")
    ref = resources.files("uap.core.prompts").joinpath(_ASSETS, name)
    if not ref.is_file():
        raise FileNotFoundError(f"Missing prompt asset: {name}")
    return ref.read_text(encoding="utf-8")


def _required_format_keys(template: str) -> set[str]:
    """``str.format`` 所需的最外层字段名（支持 ``{{`` 转义）。"""
    roots: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(template):
        if not field_name:
            continue
        root = field_name.split(".", 1)[0].split("[", 1)[0]
        roots.add(root)
    return roots


def render(prompt_id: PromptId, **kwargs: Any) -> str:
    """加载并 ``str.format``；占位符须与资产文件一致。"""
    tpl = load_raw(prompt_id)
    need = _required_format_keys(tpl)
    missing = need - kwargs.keys()
    if missing:
        raise KeyError(f"Prompt {prompt_id.value}: missing format keys {sorted(missing)}")
    return tpl.format(**kwargs)
