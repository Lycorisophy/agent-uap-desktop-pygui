"""
UAP ReAct Agent系统 - 模块入口

提供基于思考-行动-观察循环的智能体能力。
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
    # Factory
    "create_react_agent",
]
