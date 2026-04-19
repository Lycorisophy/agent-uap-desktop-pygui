"""
项目知识库（Milvus）语义检索技能，供 ReAct / Plan 按需调用。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from uap.skill.atomic_skills import AtomicSkill, SkillCategory, SkillComplexity, SkillMetadata

_LOG = logging.getLogger("uap.core.action.react.project_kb")

# 防止检索结果挤爆上下文
_MAX_HIT_CHARS = 320
_MAX_TOTAL_OBS_CHARS = 3600
_MAX_HITS_IN_TEXT = 8
_TOP_K_CAP = 20


def _format_hits(hits: list[dict[str, Any]], max_hits: int, per_cap: int, total_cap: int) -> str:
    lines: list[str] = []
    total = 0
    for i, h in enumerate(hits[:max_hits], start=1):
        text = (h.get("text") or "").strip().replace("\n", " ")
        if len(text) > per_cap:
            text = text[:per_cap] + "…"
        src = (h.get("source_name") or "").strip()
        line = f"[{i}] {src}: {text}" if src else f"[{i}] {text}"
        if total + len(line) + 1 > total_cap:
            lines.append("…（后续命中已省略）")
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


class SearchKnowledgeSkill(AtomicSkill):
    """在项目向量知识库中语义检索（非当前会话 DST 内容）。"""

    def __init__(self, project_id: str, knowledge_service: Any):
        self._project_id = (project_id or "").strip()
        self._knowledge = knowledge_service
        metadata = SkillMetadata(
            skill_id="search_knowledge",
            name="项目知识库检索",
            description=(
                "仅在需要从「已导入项目的文档/知识库」中回忆事实、定义、公式或背景，"
                "且当前对话与 system_model 摘要不足以回答时调用；"
                "不要用于本回合已明确讨论过的内容。返回若干条相关文本片段摘要。"
            ),
            category=SkillCategory.DATA,
            subcategory="knowledge",
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "检索查询，用自然语言描述要找的信息",
                    },
                    "top_k": {
                        "type": "integer",
                        "default": 5,
                        "description": "返回命中条数上限（1–20）",
                    },
                },
            },
            estimated_time=4,
            complexity=SkillComplexity.SIMPLE,
            provides_skills=["project_kb_retrieval"],
        )
        super().__init__(metadata)

    def execute(self, **kwargs) -> dict:
        query = (kwargs.get("query") or "").strip()
        if not query:
            return {"error": "query 为空", "observation": "知识库检索失败：请提供 query"}

        raw_k = kwargs.get("top_k", 5)
        try:
            top_k = int(raw_k)
        except (TypeError, ValueError):
            top_k = 5
        top_k = max(1, min(_TOP_K_CAP, top_k))

        if not self._project_id:
            return {
                "error": "缺少 project_id",
                "observation": "知识库检索失败：未绑定项目",
            }
        if self._knowledge is None:
            return {
                "error": "知识库服务未配置",
                "observation": "知识库检索不可用",
            }

        try:
            res = self._knowledge.search(self._project_id, query, top_k=top_k)
        except Exception as e:
            _LOG.exception("[search_knowledge] search failed")
            return {"error": str(e), "observation": f"知识库检索异常: {e}"}

        if not res.get("ok"):
            err = res.get("error") or "检索失败"
            return {"error": err, "observation": f"知识库检索未成功: {err}"}

        hits = res.get("hits") or []
        if not hits:
            return {
                "observation": f"知识库中未找到与「{query[:80]}」强相关的条目（可换关键词重试）。",
                "hits": [],
            }

        body = _format_hits(hits, _MAX_HITS_IN_TEXT, _MAX_HIT_CHARS, _MAX_TOTAL_OBS_CHARS)
        obs = f"知识库检索（top_k={top_k}）共 {len(hits)} 条命中，摘要如下：\n{body}"
        return {"observation": obs, "hits": hits[:_MAX_HITS_IN_TEXT]}


class MemorySearchSkill(AtomicSkill):
    """
    统一记忆检索：与 ``search_knowledge`` 共用 Milvus，语义包含「已导入文档 + 抽取写入的记忆片段」。
    """

    def __init__(self, project_id: str, knowledge_service: Any):
        self._project_id = (project_id or "").strip()
        self._knowledge = knowledge_service
        metadata = SkillMetadata(
            skill_id="memory_search",
            name="智能体记忆检索",
            description=(
                "从项目向量记忆中检索信息：包含用户上传的文档分块，以及后台从对话等抽取并写入的 "
                "记忆片段（source 常含 agent_mem 前缀）。在需要回忆跨轮事实、背景或文档要点时使用；"
                "与 search_knowledge 能力等价，便于统一命名。"
            ),
            category=SkillCategory.DATA,
            subcategory="memory",
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "检索查询，用自然语言描述要找的信息",
                    },
                    "top_k": {
                        "type": "integer",
                        "default": 5,
                        "description": "返回命中条数上限（1–20）",
                    },
                },
            },
            estimated_time=4,
            complexity=SkillComplexity.SIMPLE,
            provides_skills=["memory_rag_retrieval"],
        )
        super().__init__(metadata)

    def execute(self, **kwargs) -> dict:
        query = (kwargs.get("query") or "").strip()
        if not query:
            return {"error": "query 为空", "observation": "记忆检索失败：请提供 query"}

        raw_k = kwargs.get("top_k", 5)
        try:
            top_k = int(raw_k)
        except (TypeError, ValueError):
            top_k = 5
        top_k = max(1, min(_TOP_K_CAP, top_k))

        if not self._project_id:
            return {
                "error": "缺少 project_id",
                "observation": "记忆检索失败：未绑定项目",
            }
        if self._knowledge is None:
            return {
                "error": "知识库服务未配置",
                "observation": "记忆检索不可用",
            }

        try:
            res = self._knowledge.search(self._project_id, query, top_k=top_k)
        except Exception as e:
            _LOG.exception("[memory_search] search failed")
            return {"error": str(e), "observation": f"记忆检索异常: {e}"}

        if not res.get("ok"):
            err = res.get("error") or "检索失败"
            return {"error": err, "observation": f"记忆检索未成功: {err}"}

        hits = res.get("hits") or []
        if not hits:
            return {
                "observation": f"记忆中未找到与「{query[:80]}」强相关的条目（可换关键词重试）。",
                "hits": [],
            }

        body = _format_hits(hits, _MAX_HITS_IN_TEXT, _MAX_HIT_CHARS, _MAX_TOTAL_OBS_CHARS)
        obs = f"记忆检索（top_k={top_k}）共 {len(hits)} 条命中，摘要如下：\n{body}"
        return {"observation": obs, "hits": hits[:_MAX_HITS_IN_TEXT]}


def create_search_knowledge_skill(
    project_id: str,
    knowledge_service: Optional[Any] = None,
) -> SearchKnowledgeSkill:
    """绑定 ``project_id`` 与 ``ProjectKnowledgeService`` 的工厂。"""
    return SearchKnowledgeSkill(project_id, knowledge_service)


def create_memory_search_skill(
    project_id: str,
    knowledge_service: Optional[Any] = None,
) -> MemorySearchSkill:
    """统一记忆检索工具工厂（与知识库检索共用向量索引）。"""
    return MemorySearchSkill(project_id, knowledge_service)
