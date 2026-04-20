"""SQLite 向量知识库与工厂。"""

from __future__ import annotations

from pathlib import Path

import pytest

from uap.core.memory.knowledge.factory import create_project_knowledge_service
from uap.core.memory.knowledge.sqlite_vec_project_kb import SqliteVecProjectKnowledgeService
from uap.settings.models import EmbeddingConfig, LLMConfig, StorageConfig, UapConfig


def _cfg(tmp_path: Path, *, backend: str = "sqlite_vec") -> UapConfig:
    return UapConfig(
        llm=LLMConfig(provider="ollama", model="m", base_url="http://127.0.0.1:11434"),
        embedding=EmbeddingConfig(model="e", base_url="", dimension=32),
        storage=StorageConfig(
            milvus_backend=backend,  # type: ignore[arg-type]
            sqlite_vec_path=str(tmp_path / "kb.sqlite"),
        ),
    )


def test_factory_returns_sqlite_when_configured(tmp_path: Path) -> None:
    svc = create_project_knowledge_service(_cfg(tmp_path))
    assert isinstance(svc, SqliteVecProjectKnowledgeService)


def test_sqlite_search_top_k(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    svc = SqliteVecProjectKnowledgeService(cfg)

    def fake_embed(_t: str) -> list[float]:
        v = [0.0] * 32
        v[0] = 1.0
        return v

    monkeypatch.setattr(svc, "_embed", fake_embed)

    st = svc.status("proj-a")
    assert st.get("ok") is True
    assert st.get("row_count") == 0

    r = svc.ingest_snippets(
        "proj-a",
        [{"text": "hello world chunk one", "source_name": "s1"}],
    )
    assert r.get("ok") is True
    assert int(r.get("chunks") or 0) >= 1

    out = svc.search("proj-a", "query", top_k=3)
    assert out.get("ok") is True
    hits = out.get("hits") or []
    assert len(hits) >= 1
    assert "distance" in hits[0]
