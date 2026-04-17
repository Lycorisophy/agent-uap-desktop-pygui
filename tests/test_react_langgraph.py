"""ReAct / LangGraph / LangChain 工厂与编排回归。"""

from unittest.mock import MagicMock

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage

from uap.config import LLMConfig
from uap.infrastructure.llm.langchain_chat_model import create_langchain_chat_model
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
