"""七域分层：新旧 import 路径冒烟测试。"""


def test_settings_and_legacy_config_equivalent() -> None:
    from uap.config import UapConfig, load_config
    from uap.settings import UapConfig as U2, load_config as lc2

    assert UapConfig is U2
    assert load_config is lc2


def test_adapters_llm_and_infrastructure_llm_exports() -> None:
    from uap.adapters.llm import ModelExtractor, create_llm_chat_client
    from uap.infrastructure.llm import ModelExtractor as MX2, create_llm_chat_client as CF2

    assert ModelExtractor is MX2
    assert create_llm_chat_client is CF2


def test_persistence_and_infrastructure_persistence() -> None:
    from uap.infrastructure.persistence import ProjectStore as PS1
    from uap.persistence import ProjectStore as PS2

    assert PS1 is PS2


def test_contract_reexports_project_models() -> None:
    from uap.contract import Project, SystemModel
    from uap.project.models import Project as P2

    assert Project is P2
    assert SystemModel.__name__ == "SystemModel"


def test_delivery_uap_api() -> None:
    from uap.api import UAPApi as A1
    from uap.delivery import UAPApi as A2
    from uap.interfaces.api.uap_api import UAPApi as A3

    assert A1 is A2 is A3


def test_core_subpackages_import() -> None:
    from uap.core.prompts import PromptId
    from uap.core.constraints import DstManager
    from uap.core.memory import ProjectKnowledgeService
    from uap.core.action import ReactAgent, PlanAgent

    assert PromptId is not None
    assert DstManager is not None
    assert ProjectKnowledgeService is not None
    assert ReactAgent is not None
    assert PlanAgent is not None


def test_prompts_physical_package_loads_assets() -> None:
    from uap.core.prompts import PromptId, load_raw

    text = load_raw(PromptId.REACT_DECISION_USER)
    assert "Thought" in text or "Action" in text


def test_skills_canonical_matches_legacy_skill_package() -> None:
    from uap.core.skills import AtomicSkill
    from uap.skill import AtomicSkill as Legacy

    assert AtomicSkill is Legacy


def test_react_canonical_matches_legacy_package() -> None:
    from uap.core.action.react import DstManager as D1
    from uap.react import DstManager as D2

    assert D1 is D2
