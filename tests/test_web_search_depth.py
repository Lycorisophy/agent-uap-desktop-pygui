"""run_web_search：Tavily search_depth 与 DuckDuckGo 条数。"""

from unittest.mock import MagicMock, patch

from uap.adapters.search.web_search import run_web_search, search_tavily


def test_search_tavily_accepts_advanced_depth() -> None:
    captured: dict = {}

    def fake_post(url, json=None, **kwargs):
        captured["json"] = json
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.json = MagicMock(return_value={"results": []})
        return r

    with patch("uap.adapters.search.web_search.httpx.Client") as client_cls:
        inst = MagicMock()
        inst.__enter__ = MagicMock(return_value=inst)
        inst.__exit__ = MagicMock(return_value=False)
        inst.post = MagicMock(side_effect=fake_post)
        client_cls.return_value = inst

        search_tavily("q", 5, "k", search_depth="advanced")
        assert captured.get("json", {}).get("search_depth") == "advanced"


def test_run_web_search_passes_depth_to_tavily() -> None:
    captured: dict = {}

    def fake_post(url, json=None, **kwargs):
        captured["json"] = json
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.json = MagicMock(return_value={"results": []})
        return r

    with patch("uap.adapters.search.web_search.httpx.Client") as client_cls:
        inst = MagicMock()
        inst.__enter__ = MagicMock(return_value=inst)
        inst.__exit__ = MagicMock(return_value=False)
        inst.post = MagicMock(side_effect=fake_post)
        client_cls.return_value = inst

        run_web_search(
            "query",
            3,
            provider="tavily",
            tavily_api_key="secret",
            tavily_search_depth="advanced",
        )
        assert captured.get("json", {}).get("search_depth") == "advanced"


def test_react_deep_search_cot_suffix_present() -> None:
    from uap.config import ContextCompressionConfig
    from uap.react.dst_manager import DstManager
    from uap.react.react_agent import ReactAgent
    from unittest.mock import MagicMock
    from langchain_core.language_models.chat_models import BaseChatModel

    m = MagicMock(spec=BaseChatModel)
    m.bind_tools = lambda *a, **k: m
    dst = DstManager()
    agent = ReactAgent(
        chat_model=m,
        skills_registry={},
        dst_manager=dst,
        max_iterations=4,
        max_time_seconds=60.0,
        compression_config=ContextCompressionConfig(enabled=False),
    )
    sid = "s"
    sess = dst.create_session(sid, "t", {"deep_search_cot_mode": True, "project_id": "p"})
    body = agent.build_llm_user_content(
        "task",
        {"deep_search_cot_mode": True, "project_id": "p"},
        sess,
        [],
        session_id=sid,
        llm_round=1,
        step_id=1,
    )
    assert "深度搜索" in body and "web_search" in body
