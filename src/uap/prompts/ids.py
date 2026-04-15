"""提示词资产 ID（与 ``assets/{value}.md`` 一一对应）。"""

from enum import Enum


class PromptId(str, Enum):
    """包内资源文件名（不含扩展名）。"""

    MODEL_EXTRACTION_SYSTEM = "model_extraction_system"
    MODEL_EXTRACTION_USER_PREFIX = "model_extraction_user_prefix"

    REACT_DECISION_USER = "react_decision_user"

    SKILL_GENERATION_SYSTEM = "skill_generation_system"
    SKILL_GENERATION_USER = "skill_generation_user"
    SKILL_VALIDATION_USER = "skill_validation_user"
    SKILL_VALIDATION_SYSTEM = "skill_validation_system"

    SKILL_EXECUTOR_GUIDANCE = "skill_executor_guidance"

    DOCUMENT_EXTRACT_SYSTEM = "document_extract_system"
    DOCUMENT_EXTRACT_USER = "document_extract_user"

    RAG_REFERENCE_SYSTEM = "rag_reference_system"
    RAG_HIT_LINE = "rag_hit_line"

    SCENARIO_POWER_GRID_SYSTEM = "scenario_power_grid_system"
    SCENARIO_CUSTOM_SYSTEM = "scenario_custom_system"
