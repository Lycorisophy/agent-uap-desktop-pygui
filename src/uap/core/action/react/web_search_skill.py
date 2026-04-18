"""
UAP Web搜索技能

让ReAct Agent能够自主搜索网络获取信息。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from uap.adapters.search import run_web_search
from uap.skill.atomic_skills import AtomicSkill, SkillCategory, SkillComplexity, SkillMetadata

_LOG = logging.getLogger("uap.core.action.react.web_search")


class WebSearchSkill(AtomicSkill):
    """Web搜索技能"""

    def __init__(self, search_func: Optional[callable] = None):
        """
        初始化Web搜索技能

        Args:
            search_func: 搜索函数，签名为 (query: str) -> list[dict]
        """
        metadata = SkillMetadata(
            skill_id="web_search",
            name="网络搜索",
            description="搜索网络获取信息，用于查找复杂系统的相关资料、数据和案例",
            category=SkillCategory.DATA,
            subcategory="search",
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，应包含要搜索的概念和技术术语"
                    },
                    "num_results": {
                        "type": "integer",
                        "default": 5,
                        "description": "返回结果数量"
                    }
                }
            },
            output_schema={
                "type": "object",
                "properties": {
                    "results": {
                        "type": "array",
                        "description": "搜索结果列表"
                    },
                    "summary": {
                        "type": "string",
                        "description": "搜索结果摘要"
                    }
                }
            },
            estimated_time=5,
            complexity=SkillComplexity.SIMPLE,
            provides_skills=["information_retrieval", "data_collection"]
        )
        super().__init__(metadata)
        self._search_func = search_func

    def set_search_func(self, func: callable) -> None:
        """设置搜索函数"""
        self._search_func = func

    def execute(self, **kwargs) -> dict:
        """
        执行Web搜索

        Args:
            query: 搜索关键词
            num_results: 返回结果数量

        Returns:
            dict: 搜索结果
        """
        query = kwargs.get("query", "")
        num_results = kwargs.get("num_results", 5)

        if not query:
            return {"error": "搜索关键词不能为空", "results": [], "observation": "搜索失败：缺少查询词"}

        _LOG.info("[WebSearchSkill] Searching for: %s", query)

        try:
            if self._search_func:
                raw_results = self._search_func(query, num_results)
            else:
                # 使用默认搜索实现
                raw_results = self._default_search(query, num_results)

            # 格式化结果
            results = self._format_results(raw_results)

            observation = self._generate_observation(results, query)

            return {
                "results": results,
                "summary": f"找到 {len(results)} 条相关信息",
                "observation": observation
            }

        except Exception as e:
            _LOG.exception("[WebSearchSkill] Search failed: %s", str(e))
            return {
                "error": str(e),
                "results": [],
                "observation": f"搜索失败：{str(e)}"
            }

    def _default_search(self, query: str, num_results: int) -> list[dict]:
        """默认：DuckDuckGo 文本检索（无 API Key）。注入 ``search_func`` 时不会调用本方法。"""
        return run_web_search(query, num_results, provider="duckduckgo", tavily_api_key="")

    def _format_results(self, raw_results: list) -> list[dict]:
        """格式化搜索结果"""
        formatted = []
        for i, result in enumerate(raw_results, 1):
            if isinstance(result, dict):
                formatted.append({
                    "index": i,
                    "title": result.get("title", "无标题"),
                    "url": result.get("url", ""),
                    "snippet": result.get("snippet", result.get("description", ""))[:200]
                })
        return formatted

    def _generate_observation(self, results: list, query: str) -> str:
        """生成观察结果"""
        if not results:
            return f"未找到关于'{query}'的相关信息"

        obs = f"通过网络搜索，找到 {len(results)} 条关于'{query}'的结果：\n"
        for r in results[:3]:  # 最多显示3条
            obs += f"- {r['title']}: {r['snippet'][:100]}...\n"

        if len(results) > 3:
            obs += f"(还有 {len(results) - 3} 条结果)"

        return obs


class KnowledgeBaseSkill(AtomicSkill):
    """知识库查询技能"""

    def __init__(self, kb_func: Optional[callable] = None):
        metadata = SkillMetadata(
            skill_id="knowledge_base",
            name="知识库查询",
            description="查询本地知识库获取专业领域知识",
            category=SkillCategory.DATA,
            subcategory="knowledge",
            input_schema={
                "type": "object",
                "required": ["topic"],
                "properties": {
                    "topic": {"type": "string", "description": "查询主题"},
                    "domain": {"type": "string", "description": "专业领域"}
                }
            },
            estimated_time=3,
            complexity=SkillComplexity.SIMPLE,
            provides_skills=["domain_knowledge"]
        )
        super().__init__(metadata)
        self._kb_func = kb_func

    def execute(self, **kwargs) -> dict:
        topic = kwargs.get("topic", "")
        domain = kwargs.get("domain", "")

        if not topic:
            return {"error": "查询主题不能为空", "observation": "知识库查询失败：缺少主题"}

        try:
            if self._kb_func:
                content = self._kb_func(topic, domain)
            else:
                content = f"关于{topic}的知识库内容..."

            return {
                "content": content,
                "observation": f"从知识库获取到关于'{topic}'的信息：{content[:200]}..."
            }
        except Exception as e:
            return {"error": str(e), "observation": f"知识库查询失败：{str(e)}"}


def create_web_search_skill(search_func: callable = None) -> WebSearchSkill:
    """
    创建Web搜索技能

    Args:
        search_func: 搜索函数

    Returns:
        WebSearchSkill实例
    """
    return WebSearchSkill(search_func)


def create_knowledge_base_skill(kb_func: callable = None) -> KnowledgeBaseSkill:
    """
    创建知识库查询技能

    Args:
        kb_func: 知识库查询函数

    Returns:
        KnowledgeBaseSkill实例
    """
    return KnowledgeBaseSkill(kb_func)
