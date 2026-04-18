"""
uap.core.action.react —— **八大行动模式**里「ReAct + DST + 工具技能」的聚合导出入口
======================================================================

当前实现以 **ReAct**（``ReactAgent``）为主轴，``DstManager`` 提供 **槽位式上下文**，
``*_skill`` 提供 **原子工具**封装；**HITL** 通过 ``ReactCardIntegration`` 与 ``card`` 包协作。

新增其它行动模式（如显式 Planner）时：建议平行新建子模块（``uap/plan`` 等），
再在 ``ProjectService`` 中按配置切换，避免把多种模式的提示词揉进同一 ``_build_context``。
======================================================================
"""

from uap.core.action.react.react_agent import (
    ReactAgent,
    ReactStep,
    ReactResult,
)

from uap.core.action.react.dst_manager import (
    DstManager,
    DstState,
    ModelingStage,
)

from uap.core.action.react.web_search_skill import (
    WebSearchSkill,
    KnowledgeBaseSkill,
    create_web_search_skill,
    create_knowledge_base_skill,
)
from uap.core.action.react.file_access_skill import (
    FileAccessSkill,
    ExternalFileAccessSkill,
    create_file_access_skill,
    create_external_file_access_skill,
)
from uap.core.action.react.project_kb_skill import (
    SearchKnowledgeSkill,
    create_search_knowledge_skill,
)
from uap.core.action.react.win11_project_fs_skills import (
    create_win11_project_fs_skill_bundle,
    resolve_project_path,
)
from uap.core.action.react.card_integration import ReactCardIntegration


def create_react_agent(
    chat_model,
    skills_registry: dict | None = None,
    dst_manager: DstManager | None = None,
    max_iterations: int = 8,
    max_time_seconds: float = 120.0,
    compression_config=None,
    knowledge_service=None,
) -> ReactAgent:
    """
    创建 ReAct Agent 快捷函数

    Args:
        chat_model: LangChain ``BaseChatModel``
        skills_registry: ``skill_id`` → ``AtomicSkill``；默认由原子库元数据构造实例
        dst_manager: DST 管理器
        max_iterations: 最大迭代次数
        max_time_seconds: 最大执行时间

    Returns:
        ReactAgent 实例
    """
    from uap.skill.atomic_implemented import build_modeling_atomic_registry

    if skills_registry is None:
        skills = dict(build_modeling_atomic_registry())
    else:
        skills = skills_registry
    dst = dst_manager or DstManager()

    return ReactAgent(
        chat_model=chat_model,
        skills_registry=skills,
        dst_manager=dst,
        max_iterations=max_iterations,
        max_time_seconds=max_time_seconds,
        compression_config=compression_config,
        knowledge_service=knowledge_service,
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
    # Project KB (Milvus)
    "SearchKnowledgeSkill",
    "create_search_knowledge_skill",
    # Project workspace FS (win11_*)
    "create_win11_project_fs_skill_bundle",
    "resolve_project_path",
    # HITL
    "ReactCardIntegration",
    # Factory
    "create_react_agent",
]
