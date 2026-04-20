"""
将未处理 Episode 写入项目向量知识库（Milvus 或 SQLite，与文档块共用 source_name 区分）。

后续可替换为 LLM 结构化抽取（事件/关系/事实）再入库。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from uap.core.memory.agent_memory_persistence import AgentMemoryPersistence
    from uap.core.memory.knowledge.milvus_project_kb import ProjectKnowledgeService
    from uap.core.memory.knowledge.sqlite_vec_project_kb import SqliteVecProjectKnowledgeService

_LOG = logging.getLogger("uap.memory_extraction")


class MemoryExtractionService:
    def __init__(
        self,
        persistence: Optional["AgentMemoryPersistence"],
        knowledge: "ProjectKnowledgeService | SqliteVecProjectKnowledgeService",
        *,
        extractor_version: str = "1",
    ) -> None:
        self._persistence = persistence
        self._knowledge = knowledge
        self._extractor_version = extractor_version

    def process_unprocessed(self, project_id: str, *, limit: int = 32) -> dict[str, Any]:
        if not self._persistence or not self._persistence.enabled:
            return {"ok": False, "error": "agent_memory_disabled", "processed": 0}
        pid = (project_id or "").strip()
        if not pid:
            return {"ok": False, "error": "no_project", "processed": 0}

        eps = self._persistence.list_unprocessed(pid, limit=limit)
        if not eps:
            return {"ok": True, "processed": 0, "chunks": 0}

        snippets: list[dict[str, Any]] = []
        eids: list[str] = []
        for ep in eps:
            eid = str(ep.get("id") or "")
            st = str(ep.get("source_type") or "chat")
            body = (ep.get("content") or "").strip()
            if not eid or not body:
                continue
            snippets.append(
                {
                    "text": body,
                    "source_name": f"agent_mem|{st}|{eid}"[:512],
                }
            )
            eids.append(eid)

        if not snippets:
            return {"ok": True, "processed": 0, "chunks": 0}

        ing = self._knowledge.ingest_snippets(pid, snippets)
        if not ing.get("ok"):
            return {
                "ok": False,
                "error": ing.get("error"),
                "processed": 0,
                "chunks": 0,
            }

        last_id: str | None = None
        for eid in eids:
            self._persistence.mark_episode_processed(eid)
            last_id = eid

        self._persistence.bump_progress(
            pid,
            last_episode_id=last_id,
            delta_processed=len(eids),
            extractor_version=self._extractor_version,
        )

        _LOG.info(
            "[MemoryExtraction] project=%s episodes=%s chunks=%s",
            pid,
            len(eids),
            ing.get("chunks"),
        )
        return {
            "ok": True,
            "processed": len(eids),
            "chunks": int(ing.get("chunks") or 0),
        }
