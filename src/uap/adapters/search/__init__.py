"""第三方网络搜索适配（DuckDuckGo / Tavily）。"""

from uap.adapters.search.web_search import (
    make_web_search_callable,
    run_web_search,
    search_duckduckgo,
    search_tavily,
)

__all__ = [
    "make_web_search_callable",
    "run_web_search",
    "search_duckduckgo",
    "search_tavily",
]
