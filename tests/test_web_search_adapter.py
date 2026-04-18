"""网络搜索适配器（mock / 契约）。"""

from uap.adapters.search import run_web_search
from uap.settings.models import AgentConfig
from uap.adapters.search.web_search import make_web_search_callable


def test_run_web_search_mock() -> None:
    rows = run_web_search("test query", 3, provider="mock", tavily_api_key="")
    assert len(rows) >= 1
    assert "title" in rows[0] and "url" in rows[0]


def test_make_web_search_callable_respects_agent_config() -> None:
    ag = AgentConfig(web_search_provider="mock")
    fn = make_web_search_callable(ag)
    rows = fn("x", 2)
    assert isinstance(rows, list)
