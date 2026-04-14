"""
UAP 技能系统 - 模块入口

提供技能系统的核心接口和便捷函数。
参考 Chimera 的原子技能库设计。
"""

from uap.skill.models import (
    # 枚举
    ActionType,
    SessionStatus,
    SkillCategory,
    # 数据模型
    ActionNode,
    SkillSession,
    SkillStep,
    SkillParameter,
    ProjectSkill,
    SkillExecution,
)

from uap.skill.skill_store import SkillStore
from uap.skill.generator import SkillGenerator, SkillTemplateGenerator
from uap.skill.manager import SkillManager
from uap.skill.executor import (
    ModelingSkillExecutor,
    PredictionSkillExecutor,
    SkillSessionTracker,
)
from uap.skill.atomic_skills import (
    # 原子技能库
    SkillMetadata,
    AtomicSkill,
    SkillComplexity,
    get_atomic_skills_library,
    get_skills_by_category,
    get_skill_chain_recommendations,
)


def create_skill_manager(
    projects_dir: str,
    llm_client
) -> SkillManager:
    """
    创建技能管理器快捷函数
    
    Args:
        projects_dir: 项目根目录
        llm_client: LLM 客户端
        
    Returns:
        配置好的 SkillManager 实例
    """
    store = SkillStore(projects_dir)
    return SkillManager(store, llm_client)


def create_modeling_executor(
    skill_manager: SkillManager,
    model_extractor
) -> ModelingSkillExecutor:
    """
    创建建模技能执行器快捷函数
    
    Args:
        skill_manager: 技能管理器
        model_extractor: 模型提取器
        
    Returns:
        ModelingSkillExecutor 实例
    """
    return ModelingSkillExecutor(skill_manager, model_extractor)


def create_prediction_executor(
    skill_manager: SkillManager,
    prediction_engine
) -> PredictionSkillExecutor:
    """
    创建预测技能执行器快捷函数
    
    Args:
        skill_manager: 技能管理器
        prediction_engine: 预测引擎
        
    Returns:
        PredictionSkillExecutor 实例
    """
    return PredictionSkillExecutor(skill_manager, prediction_engine)


def create_session_tracker(
    skill_manager: SkillManager
) -> SkillSessionTracker:
    """
    创建会话追踪器快捷函数
    
    Args:
        skill_manager: 技能管理器
        
    Returns:
        SkillSessionTracker 实例
    """
    return SkillSessionTracker(skill_manager)


# 导出所有公开接口
__all__ = [
    # 枚举
    "ActionType",
    "SessionStatus",
    "SkillCategory",
    # 数据模型
    "ActionNode",
    "SkillSession",
    "SkillStep",
    "SkillParameter",
    "ProjectSkill",
    "SkillExecution",
    # 存储
    "SkillStore",
    # 生成器
    "SkillGenerator",
    "SkillTemplateGenerator",
    # 管理器
    "SkillManager",
    # 执行器
    "ModelingSkillExecutor",
    "PredictionSkillExecutor",
    "SkillSessionTracker",
    # 原子技能库
    "SkillMetadata",
    "AtomicSkill",
    "SkillComplexity",
    "get_atomic_skills_library",
    "get_skills_by_category",
    "get_skill_chain_recommendations",
    # 快捷函数
    "create_skill_manager",
    "create_modeling_executor",
    "create_prediction_executor",
    "create_session_tracker",
]
