"""
Ask 模式（只读安全 ReAct）技能白名单。

仅注册检索/阅读类工具：``web_search``、``search_knowledge``、``file_access``；
不包含数据原子技能、建模 harness、win11 写文件、Windows CLI 等。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

_LOG = __import__("logging").getLogger("uap.application.ask_mode")


def build_ask_mode_skills_registry(
    *,
    project_id: str,
    proj_dir: Path,
    cfg: Any,
    knowledge: Any,
    web_search_func: Callable | None,
    create_file_access_skill: Callable[..., Any],
    create_web_search_skill: Callable[..., Any],
    create_search_knowledge_skill: Callable[..., Any],
) -> dict[str, Any]:
    """
    构造仅含只读/搜索类技能的注册表（skill_id → AtomicSkill）。
    """
    skills_registry: dict[str, Any] = {}
    if web_search_func and getattr(cfg.agent, "web_search_enabled", True):
        skills_registry["web_search"] = create_web_search_skill(web_search_func)

    skills_registry["file_access"] = create_file_access_skill(project_folder=str(proj_dir))

    if getattr(cfg.agent, "modeling_kb_tool_enabled", True):
        skills_registry["search_knowledge"] = create_search_knowledge_skill(
            project_id, knowledge
        )

    _LOG.debug(
        "[AskMode] registry keys=%s",
        sorted(skills_registry.keys()),
    )
    return skills_registry
