"""SkillManager 前置条件：ctx / 点路径与兼容分支。"""

from unittest.mock import MagicMock

from uap.skill.manager import SkillManager
from uap.skill.models import ProjectSkill, SkillCategory


def _skill(**kwargs) -> ProjectSkill:
    base = {
        "skill_id": "s1",
        "project_id": "p1",
        "name": "n",
        "description": "d",
        "category": SkillCategory.GENERAL,
        "preconditions": [],
    }
    base.update(kwargs)
    return ProjectSkill(**base)


def test_precondition_ctx_path_truthy() -> None:
    store = MagicMock()
    store.list_skills.return_value = []
    mgr = SkillManager(store, MagicMock())
    skill = _skill(preconditions=["ctx:has_model", "context:nested.flag"])
    assert mgr._check_preconditions(
        skill, {"has_model": 1, "nested": {"flag": True}}
    )


def test_precondition_ctx_path_missing() -> None:
    store = MagicMock()
    store.list_skills.return_value = []
    mgr = SkillManager(store, MagicMock())
    skill = _skill(preconditions=["ctx:missing_key"])
    assert not mgr._check_preconditions(skill, {"other": 1})


def test_precondition_dotted_top_level() -> None:
    store = MagicMock()
    store.list_skills.return_value = []
    mgr = SkillManager(store, MagicMock())
    skill = _skill(preconditions=["existing_model"])
    assert mgr._check_preconditions(skill, {"existing_model": {"x": 1}})
    assert not mgr._check_preconditions(skill, {"existing_model": None})


def test_precondition_empty_list() -> None:
    store = MagicMock()
    store.list_skills.return_value = []
    mgr = SkillManager(store, MagicMock())
    skill = _skill(preconditions=[])
    assert mgr._check_preconditions(skill, {})
