"""ReAct / LangGraph / LangChain 工厂与编排回归。"""

import uuid
from unittest.mock import MagicMock

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk

from uap.config import ContextCompressionConfig, LLMConfig
from uap.infrastructure.llm.langchain_chat_model import create_langchain_chat_model
from uap.infrastructure.modeling_stream_hub import ModelingStreamHub
from uap.react.dst_manager import DstManager
from uap.react.lc_tools import atomic_skills_to_lc_tools
from uap.react.react_agent import ReactAgent
from uap.skill.atomic_skills import AtomicSkill, SkillMetadata, SkillCategory


def test_create_langchain_chat_model_ollama_native() -> None:
    cfg = LLMConfig(
        provider="ollama",
        api_mode="native",
        base_url="http://127.0.0.1:11434",
        model="llama3.2",
    )
    m = create_langchain_chat_model(cfg)
    assert m is not None
    assert getattr(m, "model", None) == "llama3.2"


def test_atomic_skills_to_lc_tools_empty() -> None:
    assert atomic_skills_to_lc_tools({}) == []


def test_build_llm_user_content_includes_harness_hints() -> None:
    """压缩后的提示末尾应包含编排层说明（轮次、上限、超时、ask_user）。"""
    m = MagicMock(spec=BaseChatModel)
    m.bind_tools = lambda *a, **k: m
    dst = DstManager()
    agent = ReactAgent(
        chat_model=m,
        skills_registry={},
        dst_manager=dst,
        max_iterations=8,
        max_time_seconds=300.0,
        max_ask_user_per_turn=1,
        compression_config=ContextCompressionConfig(enabled=False),
    )
    sid = str(uuid.uuid4())
    sess = dst.create_session(sid, "task text", {"project_id": "p1"})
    out = agent.build_llm_user_content(
        "task text",
        {"project_id": "p1"},
        sess,
        [],
        session_id=sid,
        llm_round=3,
        step_id=1,
    )
    assert "最大决策轮数" in out
    assert "8" in out
    assert "ReAct" in out
    assert "300" in out
    assert "当前决策轮次" in out and "3" in out


def test_parse_llm_response_multiline_thought() -> None:
    """多行 Thought 与全角冒号 Action：须完整保留思考文本。"""
    m = MagicMock(spec=BaseChatModel)
    m.bind_tools = lambda *a, **k: m
    dst = DstManager()
    agent = ReactAgent(
        chat_model=m,
        skills_registry={},
        dst_manager=dst,
        max_iterations=8,
        max_time_seconds=300.0,
        max_ask_user_per_turn=1,
        compression_config=ContextCompressionConfig(enabled=False),
    )
    text = """Thought: 第一行
第二行仍是思考
Action： ask_user
Action Input: {"question": "ok"}"""
    parsed = agent._parse_llm_response(AIMessage(content=text))
    assert "第二行仍是思考" in (parsed.get("thought") or "")
    assert (parsed.get("action") or "").strip() == "ask_user"


def test_react_graph_respects_max_iterations() -> None:
    meta = SkillMetadata(
        skill_id="echo_tool",
        name="echo",
        description="echo",
        category=SkillCategory.GENERAL,
        input_schema={
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        },
    )
    sk = AtomicSkill(meta)
    sk.set_executor(lambda self, **kw: {"observation": kw.get("msg", "")})

    m = MagicMock(spec=BaseChatModel)
    m.bind_tools = lambda *a, **k: m
    m.invoke = lambda msgs: AIMessage(
        content="",
        tool_calls=[
            {
                "name": "echo_tool",
                "args": {"parameters": {"msg": "x"}},
                "id": "1",
                "type": "tool_call",
            }
        ],
    )

    dst = DstManager()
    agent = ReactAgent(
        chat_model=m,
        skills_registry={"echo_tool": sk},
        dst_manager=dst,
        max_iterations=2,
        max_time_seconds=60.0,
    )
    r = agent.run("task", {})
    assert r.success is False
    assert r.error_message == "max_iterations"
    assert len(r.steps) >= 1


def test_react_graph_single_llm_round_after_ask_user_when_max_ask_user_is_one() -> None:
    """成功 ask_user 后默认不再进入下一轮 decide（仅一次 invoke）。"""
    ask_content = (
        "Thought: 需要澄清\n"
        "Action: ask_user\n"
        'Action Input: {"question": "请选择范围", "options": ["A", "B"]}\n'
    )
    m = MagicMock(spec=BaseChatModel)
    m.bind_tools = lambda *a, **k: m
    m.invoke = MagicMock(return_value=AIMessage(content=ask_content))

    dst = DstManager()
    agent = ReactAgent(
        chat_model=m,
        skills_registry={},
        dst_manager=dst,
        max_iterations=10,
        max_time_seconds=60.0,
        max_ask_user_per_turn=1,
    )
    r = agent.run("short task", {})
    assert m.invoke.call_count == 1
    assert r.steps[-1].action == "ask_user"
    assert r.pending_user_input is True
    assert r.success is False


def test_react_graph_two_decide_rounds_when_max_ask_user_per_turn_is_two() -> None:
    ask_content = (
        "Thought: 需要澄清\n"
        "Action: ask_user\n"
        'Action Input: {"question": "Q?", "options": []}\n'
    )
    m = MagicMock(spec=BaseChatModel)
    m.bind_tools = lambda *a, **k: m
    m.invoke = MagicMock(return_value=AIMessage(content=ask_content))

    dst = DstManager()
    agent = ReactAgent(
        chat_model=m,
        skills_registry={},
        dst_manager=dst,
        max_iterations=10,
        max_time_seconds=60.0,
        max_ask_user_per_turn=2,
    )
    r = agent.run("task", {})
    assert m.invoke.call_count == 2
    assert sum(1 for s in r.steps if s.action == "ask_user" and not s.is_error) == 2
    assert r.pending_user_input is True


def test_react_graph_stream_invokes_token_callback() -> None:
    """decide 在提供 _on_llm_token 且模型支持 stream 时走流式路径。"""
    pieces = [AIMessageChunk(content="hel"), AIMessageChunk(content="lo")]

    m = MagicMock(spec=BaseChatModel)
    m.bind_tools = lambda *a, **k: m
    m.stream = MagicMock(return_value=iter(pieces))

    tokens: list[str] = []

    def on_t(t: str) -> None:
        tokens.append(t)

    dst = DstManager()
    agent = ReactAgent(
        chat_model=m,
        skills_registry={},
        dst_manager=dst,
        max_iterations=2,
        max_time_seconds=60.0,
    )
    r = agent.run("x", {"_on_llm_token": on_t})
    assert "".join(tokens) == "hello"
    assert m.stream.called
    assert not m.invoke.called
    # 流式合并后的纯文本无 Thought/Action 行时，解析器会把空 action 视为结束路径之一
    assert r.steps[-1].action == "FINAL_ANSWER"


def test_modeling_stream_hub_poll_returns_result_on_finish() -> None:
    hub = ModelingStreamHub()
    hub.create("s1")
    hub.append_token("s1", "a")
    p1 = hub.poll("s1")
    assert p1["ok"] is True
    assert p1["tokens"] == ["a"]
    assert p1["done"] is False
    hub.finish("s1", {"ok": True, "message": "done"})
    p2 = hub.poll("s1")
    assert p2["done"] is True
    assert p2["result"] == {"ok": True, "message": "done"}
