"""建模入口 mode 分发与 mode_used / mode_requested。"""

from __future__ import annotations

import unittest.mock as mock

import pytest

from uap.application.project_service import ProjectService


@pytest.fixture
def svc():
    store = mock.MagicMock()
    cfg = mock.MagicMock()
    cfg.llm = mock.MagicMock()
    cfg.agent.modeling_agent_mode = "react"
    cfg.context_compression = mock.MagicMock()
    svc = ProjectService.__new__(ProjectService)
    svc._store = store
    svc._cfg = cfg
    svc._knowledge = mock.MagicMock()
    svc._extractor = mock.MagicMock()
    return svc


def test_react_mode_calls_run_react(svc):
    proj = mock.MagicMock()
    proj.system_model = None
    proj.name = "P"
    proj.folder_path = ""
    proj.workspace = ""
    svc._store.get_project.return_value = proj

    with mock.patch.object(svc, "_run_react_modeling", return_value={"ok": True}) as m_r, mock.patch.object(
        svc, "_run_plan_modeling"
    ) as m_p, mock.patch(
        "uap.application.project_service.create_langchain_chat_model",
        return_value=mock.MagicMock(),
    ):
        out = svc.react_modeling("pid", "hello", mode="react")
    m_r.assert_called_once()
    m_p.assert_not_called()
    assert out["mode_requested"] == "react"
    assert out["mode_used"] == "react"


def test_plan_mode_calls_run_plan(svc):
    proj = mock.MagicMock()
    proj.system_model = None
    proj.name = "P"
    proj.folder_path = ""
    proj.workspace = ""
    svc._store.get_project.return_value = proj

    with mock.patch.object(svc, "_run_plan_modeling", return_value={"ok": True}) as m_p, mock.patch.object(
        svc, "_run_react_modeling"
    ) as m_r, mock.patch(
        "uap.application.project_service.create_langchain_chat_model",
        return_value=mock.MagicMock(),
    ):
        out = svc.react_modeling("pid", "hello", mode="plan")
    m_p.assert_called_once()
    m_r.assert_not_called()
    assert out["mode_used"] == "plan"


def test_auto_uses_decide(svc):
    proj = mock.MagicMock()
    proj.system_model = None
    proj.name = "P"
    proj.folder_path = ""
    proj.workspace = ""
    svc._store.get_project.return_value = proj
    llm = mock.MagicMock()

    with mock.patch.object(svc, "_decide_mode_by_task", return_value="plan") as m_d, mock.patch.object(
        svc, "_run_plan_modeling", return_value={"ok": True}
    ), mock.patch.object(svc, "_run_react_modeling"), mock.patch(
        "uap.application.project_service.create_langchain_chat_model",
        return_value=llm,
    ):
        out = svc.react_modeling("pid", "task", mode="auto")
    m_d.assert_called_once()
    assert out["mode_requested"] == "auto"
    assert out["mode_used"] == "plan"


def test_unknown_mode_fallback_react(svc):
    proj = mock.MagicMock()
    proj.system_model = None
    proj.name = "P"
    proj.folder_path = ""
    proj.workspace = ""
    svc._store.get_project.return_value = proj

    with mock.patch.object(svc, "_run_react_modeling", return_value={"ok": True}), mock.patch(
        "uap.application.project_service.create_langchain_chat_model",
        return_value=mock.MagicMock(),
    ):
        out = svc.react_modeling("pid", "x", mode="weird")
    assert out["mode_used"] == "react"


def test_plan_modeling_delegates():
    svc = ProjectService.__new__(ProjectService)
    svc.react_modeling = mock.Mock(return_value={"ok": True})
    ProjectService.plan_modeling(svc, "p", "m")
    svc.react_modeling.assert_called_once()
    assert svc.react_modeling.call_args.kwargs.get("mode") == "plan"


def test_plan_step_to_react_shape():
    from uap.application.project_service import ProjectService
    from uap.plan.plan_agent import PlanStep, StepStatus

    svc = ProjectService.__new__(ProjectService)
    s = PlanStep(
        step_id=2,
        description="d",
        tool_name="ask_user",
        tool_params={"question": "q"},
        status=StepStatus.COMPLETED,
        observation="obs",
        start_time=1.0,
        end_time=1.5,
    )
    d = svc._plan_step_to_react_step_dict(s)
    assert d["step_id"] == 2
    assert d["action"] == "ask_user"
    assert d["action_input"] == {"question": "q"}
    assert d["observation"] == "obs"
    assert d["is_error"] is False
    assert d["duration_ms"] == 500
