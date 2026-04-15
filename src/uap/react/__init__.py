"""
uap.react —— **八大行动模式**里「ReAct + DST + 工具技能」的聚合导出入口
======================================================================

当前实现以 **ReAct**（``ReactAgent``）为主轴，``DstManager`` 提供 **槽位式上下文**，
``*_skill`` 提供 **原子工具**封装；**HITL** 通过 ``ReactCardIntegration`` 与 ``card`` 包协作。

新增其它行动模式（如显式 Planner）时：建议平行新建子模块（``uap/plan`` 等），
再在 ``ProjectService`` 中按配置切换，避免把多种模式的提示词揉进同一 ``_build_context``。
======================================================================
"""

from uap.react.react_agent import (
    ReactAgent,
    ReactStep,
    ReactResult,
)

from uap.react.dst_manager import (
    DstManager,
    DstState,
    ModelingStage,
)

from uap.react.web_search_skill import (
    WebSearchSkill,
    KnowledgeBaseSkill,
    create_web_search_skill,
    create_knowledge_base_skill,
)
from uap.react.file_access_skill import (
    FileAccessSkill,
    ExternalFileAccessSkill,
    create_file_access_skill,
    create_external_file_access_skill,
)
from uap.react.card_integration import ReactCardIntegration


def create_react_agent(
    llm_client,
    skills_registry: dict = None,
    dst_manager: DstManager = None,
    max_iterations: int = 10,
    max_time_seconds: float = 120.0
) -> ReactAgent:
    """
    创建ReAct Agent快捷函数

    Args:
        llm_client: LLM客户端
        skills_registry: 技能注册表
        dst_manager: DST管理器
        max_iterations: 最大迭代次数
        max_time_seconds: 最大执行时间

    Returns:
        ReactAgent实例
    """
    from uap.skill.atomic_skills import get_atomic_skills_library

    skills = skills_registry or get_atomic_skills_library()
    dst = dst_manager or DstManager()

    return ReactAgent(
        llm_client=llm_client,
        skills_registry=skills,
        dst_manager=dst,
        max_iterations=max_iterations,
        max_time_seconds=max_time_seconds
    )


__all__ = [
    # ReAct Agent
    "ReactAgent",
    "ReactStep",
    "ReactResult",
    # DST
    "DstManager",
    "DstState",
    "ModelingStage",
    # Web Skills
    "WebSearchSkill",
    "KnowledgeBaseSkill",
    "create_web_search_skill",
    "create_knowledge_base_skill",
    # File Access Skills
    "FileAccessSkill",
    "ExternalFileAccessSkill",
    "create_file_access_skill",
    "create_external_file_access_skill",
    # HITL
    "ReactCardIntegration",
    # Factory
    "create_react_agent",
]
