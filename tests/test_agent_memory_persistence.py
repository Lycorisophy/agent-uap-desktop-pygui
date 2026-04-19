"""Episode / extraction_progress SQLite 持久化。"""

from __future__ import annotations

import pytest

from uap.core.memory.agent_memory_persistence import AgentMemoryPersistence


@pytest.fixture
def mem_db():
    # :memory: 避免 Windows 下临时文件删除时 SQLite 仍占用句柄
    return AgentMemoryPersistence(":memory:")


def test_insert_and_list_unprocessed(mem_db: AgentMemoryPersistence):
    eid = mem_db.insert_episode("p1", "hello user", source_type="chat")
    assert eid
    pending = mem_db.list_unprocessed("p1")
    assert len(pending) == 1
    assert pending[0]["content"] == "hello user"


def test_mark_processed_and_stats(mem_db: AgentMemoryPersistence):
    eid = mem_db.insert_episode("p2", "x", source_type="chat")
    assert eid
    mem_db.mark_episode_processed(eid)
    assert mem_db.list_unprocessed("p2") == []
    st = mem_db.stats("p2")
    assert st.get("ok") is True
    assert st.get("episode_total") == 1
    assert st.get("episode_pending") == 0


def test_bump_progress(mem_db: AgentMemoryPersistence):
    mem_db.bump_progress("p3", last_episode_id="e1", delta_processed=2)
    mem_db.bump_progress("p3", last_episode_id="e2", delta_processed=1)
    with mem_db._connect() as conn:
        mem_db._ensure_schema(conn)
        row = conn.execute(
            "SELECT total_episodes_processed FROM extraction_progress WHERE project_id=?",
            ("p3",),
        ).fetchone()
    assert row and int(row[0]) == 3
