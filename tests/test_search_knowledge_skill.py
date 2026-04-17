"""search_knowledge 项目知识库技能。"""

from __future__ import annotations

import unittest.mock as mock

from uap.react.project_kb_skill import SearchKnowledgeSkill, create_search_knowledge_skill


def test_create_factory_returns_skill():
    kb = mock.MagicMock()
    sk = create_search_knowledge_skill("proj-1", kb)
    assert isinstance(sk, SearchKnowledgeSkill)
    assert sk.metadata.skill_id == "search_knowledge"


def test_execute_empty_query():
    kb = mock.MagicMock()
    sk = SearchKnowledgeSkill("p1", kb)
    out = sk.execute(query="   ")
    assert "error" in out
    assert "失败" in out["observation"]


def test_execute_formats_hits_and_truncates():
    kb = mock.MagicMock()
    kb.search.return_value = {
        "ok": True,
        "hits": [
            {"text": "x" * 500, "source_name": "doc.md"},
            {"text": "short", "source_name": "b.txt"},
        ],
    }
    sk = SearchKnowledgeSkill("p1", kb)
    out = sk.execute(query="销量", top_k=3)
    assert "error" not in out
    obs = out["observation"]
    assert "知识库检索" in obs
    assert "doc.md" in obs
    assert len(obs) < 4500
    kb.search.assert_called_once_with("p1", "销量", top_k=3)


def test_execute_search_not_ok():
    kb = mock.MagicMock()
    kb.search.return_value = {"ok": False, "error": "无集合"}
    sk = SearchKnowledgeSkill("p1", kb)
    out = sk.execute(query="q")
    assert "error" in out


def test_execute_no_hits():
    kb = mock.MagicMock()
    kb.search.return_value = {"ok": True, "hits": []}
    sk = SearchKnowledgeSkill("p1", kb)
    out = sk.execute(query="anything")
    assert "未找到" in out["observation"]
