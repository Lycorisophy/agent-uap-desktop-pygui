"""建模前意图/场景分类：rounds=0 仍走分类；模式注入提示词。"""

from __future__ import annotations

import unittest.mock as mock

import pytest

from uap.application.modeling_intent_classifier import (
    classify_intent_scene,
    format_execution_mode_hint,
    run_modeling_intent_scene_if_enabled,
)
from uap.config import UapConfig


@pytest.fixture
def cfg_zero_rounds():
    c = UapConfig()
    c.agent.modeling_intent_context_rounds = 0
    return c


def test_run_modeling_intent_rounds_zero_still_classifies(cfg_zero_rounds):
    with mock.patch(
        "uap.application.modeling_intent_classifier.classify_intent_scene"
    ) as m_cls:
        m_cls.return_value = {
            "classified_intent": "general",
            "classified_scene": "通用",
            "classified_read_only_fit": None,
        }
        out = run_modeling_intent_scene_if_enabled(
            cfg_zero_rounds,
            [{"role": "user", "content": "hello"}],
            "hello",
            mode_requested="plan",
        )
    m_cls.assert_called_once()
    args, kwargs = m_cls.call_args
    assert "[用户] hello" in args[1]
    assert kwargs.get("mode_requested") == "plan"
    assert out["classified_intent"] == "general"


def test_format_execution_mode_hint_covers_modes():
    assert "react" in format_execution_mode_hint("react").lower()
    assert "plan" in format_execution_mode_hint("plan").lower()
    assert "auto" in format_execution_mode_hint("auto").lower()
    ask_h = format_execution_mode_hint("ask")
    assert "ask" in ask_h.lower() or "只读" in ask_h
    assert "read_only_fit" in ask_h.lower() or "read_only_fit" in ask_h


def test_format_execution_mode_hint_scheduled():
    h = format_execution_mode_hint("scheduled")
    assert "定时任务" in h or "scheduled" in h.lower()
    assert "scheduled_next" in h or "意图" in h


def test_classify_intent_scheduled_parses_scheduled_next(cfg_zero_rounds):
    fake = mock.MagicMock()
    fake.invoke = mock.MagicMock(
        return_value={
            "content": '{"intent":"prediction","scene":"通用","scheduled_next":"plan"}',
        }
    )
    with mock.patch(
        "uap.application.modeling_intent_classifier.create_langchain_chat_model",
        return_value=fake,
    ):
        out = classify_intent_scene(
            cfg_zero_rounds,
            "[用户] x",
            "x",
            mode_requested="scheduled",
        )
    assert out["classified_intent"] == "prediction"
    assert out["classified_scheduled_next"] == "plan"


def test_classify_intent_scheduled_invalid_next_falls_back_to_prediction(cfg_zero_rounds):
    fake = mock.MagicMock()
    fake.invoke = mock.MagicMock(
        return_value={
            "content": '{"intent":"analysis","scene":"通用","scheduled_next":"bogus"}',
        }
    )
    with mock.patch(
        "uap.application.modeling_intent_classifier.create_langchain_chat_model",
        return_value=fake,
    ):
        out = classify_intent_scene(
            cfg_zero_rounds,
            "[用户] x",
            "x",
            mode_requested="scheduled",
        )
    assert out["classified_scheduled_next"] == "prediction"
