"""将 ``AtomicSkill`` 注册表转为 LangChain ``BaseTool`` 列表（供 ``bind_tools``）。"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from uap.skill.atomic_skills import AtomicSkill

_LOG = logging.getLogger("uap.react.lc_tools")


class SkillParameters(BaseModel):
    """与技能 ``input_schema`` 对齐的 JSON 对象参数。"""

    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="工具参数对象（字段名与技能 input_schema 一致）。",
    )


def _serialize_execute_result(result: Any) -> str:
    if isinstance(result, dict):
        if result.get("error"):
            return str(result["error"])
        return str(
            result.get("observation", "")
            or result.get("result", "")
            or json.dumps(result, ensure_ascii=False, default=str)
        )
    return str(result)


def _run_atomic_skill(skill: AtomicSkill, kwargs: dict[str, Any]) -> str:
    valid, errors = skill.validate_input(**kwargs)
    if not valid:
        return "参数验证失败: " + ", ".join(errors)
    try:
        out = skill.execute(**kwargs)
        return _serialize_execute_result(out)
    except Exception as e:
        _LOG.exception("[lc_tools] skill %s failed", skill.metadata.skill_id)
        return f"执行失败: {e}"


def atomic_skills_to_lc_tools(skills: dict[str, AtomicSkill]) -> list[StructuredTool]:
    """每个技能一个 StructuredTool，名称与 ``skill_id`` 一致。"""
    out: list[StructuredTool] = []
    for skill_id, skill in skills.items():
        out.append(_one_tool(skill_id, skill))
    return out


def _one_tool(skill_id: str, skill: AtomicSkill) -> StructuredTool:
    schema_hint = ""
    if skill.metadata.input_schema:
        try:
            schema_hint = json.dumps(skill.metadata.input_schema, ensure_ascii=False)[:1800]
        except (TypeError, ValueError):
            schema_hint = str(skill.metadata.input_schema)[:1800]

    desc = skill.metadata.description
    if schema_hint:
        desc = f"{desc}\n\ninput_schema:\n{schema_hint}"

    def _invoke(parameters: dict[str, Any]) -> str:
        return _run_atomic_skill(skill, parameters)

    return StructuredTool.from_function(
        name=skill_id,
        description=desc,
        func=_invoke,
        args_schema=SkillParameters,
    )
