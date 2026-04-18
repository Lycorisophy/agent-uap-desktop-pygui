"""
网络搜索防腐层：DuckDuckGo（免费）与 Tavily（API Key）。

供 ``WebSearchSkill`` 与 API 注入的 ``search_func`` 使用。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

import httpx

if TYPE_CHECKING:
    from uap.settings.models import AgentConfig

_LOG = logging.getLogger("uap.adapters.search")


def _search_mock(query: str, num_results: int) -> list[dict[str, Any]]:
    n = max(1, min(int(num_results), 10))
    return [
        {
            "title": f"示例结果（mock）— {query[:40]}",
            "url": "https://example.com",
            "snippet": "当前为 mock 提供商，未发起真实网络请求。请在配置中将 web_search_provider 设为 duckduckgo 或 tavily。",
        }
        for _ in range(min(n, 3))
    ]


def search_duckduckgo(query: str, max_results: int) -> list[dict[str, Any]]:
    """使用 duckduckgo-search 库做文本检索（无需 API Key）。"""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        _LOG.warning("未安装 duckduckgo-search，无法使用 DuckDuckGo 检索。请: pip install duckduckgo-search")
        return []

    q = (query or "").strip()
    if not q:
        return []

    n = max(1, min(int(max_results), 25))
    out: list[dict[str, Any]] = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(q, max_results=n):
                out.append(
                    {
                        "title": str(r.get("title") or ""),
                        "url": str(r.get("href") or ""),
                        "snippet": (str(r.get("body") or ""))[:2000],
                    }
                )
    except Exception as e:
        _LOG.exception("DuckDuckGo 搜索失败: %s", e)
    return out


def search_tavily(query: str, max_results: int, api_key: str) -> list[dict[str, Any]]:
    """Tavily Search API：https://docs.tavily.com"""
    key = (api_key or "").strip()
    if not key:
        return []
    q = (query or "").strip()
    if not q:
        return []

    n = max(1, min(int(max_results), 20))
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": key,
                    "query": q,
                    "max_results": n,
                    "search_depth": "basic",
                },
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        _LOG.exception("Tavily 搜索失败: %s", e)
        return []

    out: list[dict[str, Any]] = []
    for item in data.get("results") or []:
        body = item.get("content") or item.get("raw_content") or ""
        out.append(
            {
                "title": str(item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "snippet": str(body)[:2000],
            }
        )
    return out


def run_web_search(
    query: str,
    num_results: int,
    *,
    provider: str = "duckduckgo",
    tavily_api_key: str = "",
) -> list[dict[str, Any]]:
    """
    统一入口：按提供商执行搜索，返回 ``[{title, url, snippet}, ...]``。
    """
    prov = (provider or "duckduckgo").strip().lower()
    if prov == "mock":
        return _search_mock(query, num_results)
    if prov == "tavily":
        key = (tavily_api_key or "").strip()
        if not key:
            _LOG.warning("web_search_provider=tavily 但未配置 tavily_api_key，回退到 DuckDuckGo")
            return search_duckduckgo(query, num_results)
        return search_tavily(query, num_results, key)
    return search_duckduckgo(query, num_results)


def make_web_search_callable(agent: "AgentConfig") -> Callable[[str, int], list[dict[str, Any]]]:
    """根据 ``AgentConfig`` 构造 ``(query, num_results) -> results``，供建模管线注入。"""

    def _fn(query: str, num_results: int = 5) -> list[dict[str, Any]]:
        return run_web_search(
            query,
            num_results,
            provider=agent.web_search_provider,
            tavily_api_key=agent.tavily_api_key or "",
        )

    return _fn
