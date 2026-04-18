"""提示词资产加载、占位符与 ReAct 解析契约回归。"""

from unittest.mock import MagicMock

from uap.infrastructure.llm.model_extractor import ModelExtractor
from uap.prompts import PromptId, load_raw, render
from uap.react.react_agent import ReactAgent


def test_all_prompt_assets_load() -> None:
    for pid in PromptId:
        text = load_raw(pid)
        assert isinstance(text, str)
        assert len(text.strip()) > 0


def test_render_react_decision_contains_parser_contract() -> None:
    text = render(
        PromptId.REACT_DECISION_USER,
        task="测试任务",
        system_model="",
        dst_summary="当前状态: 新会话",
        skills_desc="- file_access: 读文件",
        trajectory="",
    )
    assert "Thought:" in text
    assert "Action:" in text
    assert "Action Input:" in text
    assert "FINAL_ANSWER:" in text
    assert "ask_user" in text


def test_model_extractor_parse_minimal_json() -> None:
    ext = ModelExtractor(client=MagicMock())
    payload = (
        '{"variables":[{"name":"x","type":"continuous","description":"d","unit":""}],'
        '"relations":[],"constraints":[],"confidence":0.9,"reasoning":"ok"}'
    )
    result = ext._parse_response(payload)
    assert result.success
    assert result.model is not None
    assert len(result.model.variables) == 1
    assert result.model.variables[0].name == "x"


def test_model_extractor_maps_semantic_variable_types() -> None:
    """提示词契约中的 categorical / binary 等须落到 Variable.value_type。"""
    ext = ModelExtractor(client=MagicMock())
    payload = (
        '{"variables":['
        '{"name":"w","type":"categorical","description":"","unit":""},'
        '{"name":"b","type":"binary","description":"","unit":""}'
        '],"relations":[],"constraints":[],"confidence":0.5,"reasoning":""}'
    )
    result = ext._parse_response(payload)
    assert result.success and result.model is not None
    assert result.model.variables[0].value_type == "str"
    assert result.model.variables[1].value_type == "bool"


def test_model_extractor_maps_constraint_types_from_prompt() -> None:
    ext = ModelExtractor(client=MagicMock())
    payload = (
        '{"variables":[{"name":"x","type":"continuous","description":"","unit":""}],'
        '"relations":[],"constraints":['
        '{"type":"range","expression":"0<=x<=1","description":"d"}'
        '],"confidence":0.5,"reasoning":""}'
    )
    result = ext._parse_response(payload)
    assert result.success and result.model is not None
    assert result.model.constraints[0].constraint_type == "boundary"


def test_react_parse_llm_response_basic() -> None:
    agent = ReactAgent(
        chat_model=MagicMock(),
        skills_registry={},
        dst_manager=MagicMock(),
    )
    raw = """Thought: 思考一步
Action: file_access
Action Input: {"action": "list", "path": "."}
"""
    out = agent._parse_llm_response(raw)
    assert out["thought"] == "思考一步"
    assert out["action"] == "file_access"
    assert out["action_input"] == {"action": "list", "path": "."}

    ollama_dict = {
        "message": {
            "role": "assistant",
            "content": raw,
        }
    }
    out2 = agent._parse_llm_response(ollama_dict)
    assert out2["action"] == "file_access"
