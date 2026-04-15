"""原子技能库只读 API。"""

from __future__ import annotations

from typing import Optional


class SkillsApiMixin:
    def get_atomic_skills(self, category: Optional[str] = None) -> list[dict]:
        """Get atomic skills library"""
        if category:
            from uap.skill.atomic_skills import get_skills_by_category, SkillCategory

            try:
                cat = SkillCategory(category)
                skills = get_skills_by_category(cat)
                return [meta.to_dict() for meta in skills.values()]
            except ValueError:
                return []
        return [meta.to_dict() for meta in self.atomic_skills.values()]

    def get_skill_chain_recommendations(self, task_type: str) -> list[list[str]]:
        """Get skill chain recommendations"""
        from uap.skill.atomic_skills import get_skill_chain_recommendations as get_recs

        return get_recs(task_type)
