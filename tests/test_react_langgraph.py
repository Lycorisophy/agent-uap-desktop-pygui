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
from uap.react.react_agent import ReactAgent, ReactStep
from uap.react.react_graph import _repeated_failure_circuit_tripped
from uap.skill.atomic_skills import AtomicSkill, SkillMetadata, SkillCategory


def test_repeated_failure_circuit_tripped_file_access() -> None:
    """连续 3 次同一工具且均失败时熔断。"""
    steps = [
        ReactStep(step_id=1, action="file_access", is_error=True),
        ReactStep(step_id=2, action="file_access", is_error=True),
        ReactStep(step_id=3, action="file_access", is_error=True),
    ]
    assert _repeated_failure_circuit_tripped(steps) is True


def test_repeated_failure_circuit_not_tripped_if_mixed_tools() -> None:
    steps = [
        ReactStep(step_id=1, action="file_access", is_error=True),
        ReactStep(step_id=2, action="search_knowledge", is_error=True),
        ReactStep(step_id=3, action="file_access", is_error=True),
    ]
    assert _repeated_failure_circuit_tripped(steps) is False


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


def test_parse_llm_response_list_content_blocks() -> None:
    """与流式聚合一致：content 为块列表时须解析出 Action（勿依赖 str(list)）。"""
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
    inner = (
        "Thought: 需要澄清\n"
        "Action: ask_user\n"
        'Action Input: {"question": "请说明时间范围", "options": ["日", "周"]}\n'
    )
    msg = AIMessage(content=[{"type": "text", "text": inner}])
    parsed = agent._parse_llm_response(msg)
    assert (parsed.get("action") or "").strip() == "ask_user"
    assert parsed.get("action_input", {}).get("question")


def test_parse_llm_response_chinese_action_labels() -> None:
    """与轨迹区「思考/行动/观察」一致时，模型常输出中文「行动：」须能解析。"""
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
    text = (
        "思考: 需要澄清范围\n"
        "行动： ask_user\n"
        '行动输入： {"question": "预测哪项指标？", "options": ["温度", "降水"]}\n'
    )
    parsed = agent._parse_llm_response(AIMessage(content=text))
    assert (parsed.get("action") or "").strip() == "ask_user"
    assert parsed.get("action_input", {}).get("question")


def test_parse_llm_response_inline_action_not_line_start() -> None:
    """模型在句号后直接接 Action:（非行首），须能解析。"""
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
    text = (
        "先查看数据目录。Action: file_access\n"
        'Action Input: {"action": "list", "path": "data"}\n'
    )
    parsed = agent._parse_llm_response(AIMessage(content=text))
    assert (parsed.get("action") or "").strip() == "file_access"


def test_parse_llm_response_markdown_bold_action() -> None:
    """模型输出 **Action**: 时回退解析仍能得到技能名。"""
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
    text = "**Thought**: 追问\n**Action**: ask_user\n**Action Input**: {\"question\": \"q\"}\n"
    parsed = agent._parse_llm_response(AIMessage(content=text))
    assert (parsed.get("action") or "").strip() == "ask_user"


def test_react_graph_stream_list_content_blocks_parsed() -> None:
    """decide 流式路径合并块列表后须能走 ask_user，而非 empty_action。"""
    inner = (
        "Thought: t\n"
        "Action: ask_user\n"
        'Action Input: {"question": "Q", "options": []}\n'
    )
    pieces = [AIMessageChunk(content=[{"type": "text", "text": inner}])]

    m = MagicMock(spec=BaseChatModel)
    m.bind_tools = lambda *a, **k: m
    m.stream = MagicMock(return_value=iter(pieces))

    dst = DstManager()
    agent = ReactAgent(
        chat_model=m,
        skills_registry={},
        dst_manager=dst,
        max_iterations=4,
        max_time_seconds=60.0,
        max_ask_user_per_turn=1,
    )
    r = agent.run("task", {"_on_llm_token": lambda _: None})
    assert not any(s.error_message == "empty_action" for s in r.steps)
    assert r.steps[-1].action == "ask_user"


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
    final_text = "Thought: x\nFINAL_ANSWER: ok\n"
    pieces = [
        AIMessageChunk(content=final_text[:8]),
        AIMessageChunk(content=final_text[8:]),
    ]

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
    assert "".join(tokens) == final_text
    assert m.stream.called
    assert not m.invoke.called
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
