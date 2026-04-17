"""建模快照是否有结构化内容与用户文案。"""

from types import SimpleNamespace

from uap.application.project_service import ProjectService
from uap.project.models import SystemModel, Variable


def test_modeling_snapshot_substantive_empty() -> None:
    assert ProjectService._modeling_snapshot_substantive(None) is False
    assert ProjectService._modeling_snapshot_substantive(SystemModel(name="x")) is False


def test_modeling_snapshot_substantive_with_variable() -> None:
    m = SystemModel(
        name="t",
        variables=[Variable(name="a", description="d", value_type="float", unit="u")],
    )
    assert ProjectService._modeling_snapshot_substantive(m) is True


def test_generate_response_success_without_substance() -> None:
    ps = ProjectService.__new__(ProjectService)  # 仅测文案，不初始化 store
    result = SimpleNamespace(
        pending_user_input=False,
        success=True,
        error_message=None,
        steps=[],
    )
    msg = ProjectService._generate_response_message(ps, result, SystemModel(name="n"))
    assert "尚未沉淀" in msg
    assert "建模完成" not in msg
