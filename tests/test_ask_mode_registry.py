"""Ask 模式技能白名单。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from uap.application.ask_mode_registry import build_ask_mode_skills_registry
from uap.config import UapConfig


def test_build_ask_mode_skills_registry_minimal_keys() -> None:
    cfg = UapConfig()
    root = Path(".")
    ws = MagicMock()
    reg = build_ask_mode_skills_registry(
        project_id="p1",
        proj_dir=root,
        cfg=cfg,
        knowledge=ws,
        web_search_func=lambda q, num_results=5: [],
        create_file_access_skill=lambda **kw: MagicMock(metadata=MagicMock(skill_id="file_access")),
        create_web_search_skill=lambda fn: MagicMock(metadata=MagicMock(skill_id="web_search")),
        create_search_knowledge_skill=lambda pid, k: MagicMock(
            metadata=MagicMock(skill_id="search_knowledge")
        ),
    )
    assert "file_access" in reg
    assert "web_search" in reg
    assert "search_knowledge" in reg
    assert "extract_model" not in reg
    assert len(reg) == 3
