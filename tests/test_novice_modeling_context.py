"""小白友好：模型摘要注入、ReAct 策略措辞、极短任务占位。"""

from unittest.mock import MagicMock

from uap.prompts import PromptId, load_raw, render
from uap.react.context_helpers import format_system_model_for_prompt
from uap.react.react_agent import ReactAgent
from uap.skill.models import SkillSession


def test_format_system_model_empty() -> None:
    assert format_system_model_for_prompt(None) == ""
    assert format_system_model_for_prompt({}) == ""


def test_format_system_model_summary() -> None:
    data = {
        "name": "天气草图",
        "description": "测试",
        "confidence": 0.4,
        "variables": [
            {"name": "temperature", "description": "气温", "unit": "°C", "value_type": "float"}
        ],
        "relations": [],
        "constraints": [],
    }
    s = format_system_model_for_prompt(data)
    assert "【当前项目已有模型摘要】" in s
    assert "temperature" in s
    assert "0.4" in s


def test_react_prompt_novice_policy_in_asset() -> None:
    raw = load_raw(PromptId.REACT_DECISION_USER)
    assert "一句话" in raw or "一句话目标" in raw
    assert "ask_user" in raw


def test_build_context_uses_existing_model_when_no_system_model() -> None:
    agent = ReactAgent(
        llm_client=MagicMock(),
        skills_registry={},
        dst_manager=MagicMock(),
    )
    dst = SkillSession(session_id="sid", project_id="pid", user_query="预测气温")
    ctx = agent._build_context(
        "想预测本市下周气温",
        {
            "existing_model": {
                "name": "m",
                "variables": [
                    {
                        "name": "T",
                        "description": "气温",
                        "unit": "°C",
                        "value_type": "float",
                    }
                ],
                "relations": [],
                "constraints": [],
            }
        },
        dst,
    )
    assert "【当前项目已有模型摘要】" in ctx
    assert "T" in ctx


def test_short_user_goal_renders_react_template() -> None:
    """三条极短目标句：模板渲染不抛错且保留解析契约关键字。"""
    goals = [
        "想预测本市下周气温",
        "想看公司明年营收走势",
        "想猜明天大盘涨跌",
    ]
    for g in goals:
        text = render(
            PromptId.REACT_DECISION_USER,
            task=g,
            system_model="",
            dst_summary="DST状态: 新会话",
            skills_desc="- extract_model: 测试",
            trajectory="",
        )
        assert "Thought:" in text and "FINAL_ANSWER:" in text
        assert g in text


def test_model_extraction_asset_uncertainty_guidance() -> None:
    sys_prompt = load_raw(PromptId.MODEL_EXTRACTION_SYSTEM)
    assert "confidence" in sys_prompt
    assert "待澄清" in sys_prompt or "reasoning" in sys_prompt
