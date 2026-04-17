"""项目空间 conversations/active.json 与 history 归档。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from uap.infrastructure.persistence.project_store import ProjectStore


@pytest.fixture
def store(tmp_path: Path) -> ProjectStore:
    return ProjectStore(tmp_path)


def test_messages_roundtrip_in_workspace(store: ProjectStore, tmp_path: Path) -> None:
    pid = store.create_project("T", "").id
    project = store.get_project(pid)
    ws = Path(project.workspace)
    msgs = [
        {"role": "user", "content": "hello", "created_at": "2026-01-01T00:00:00"},
        {"role": "assistant", "content": "hi", "created_at": "2026-01-01T00:01:00"},
    ]
    store.save_messages(pid, msgs)
    active = ws / "conversations" / "active.json"
    assert active.is_file()
    assert store.load_messages(pid) == msgs


def test_archive_and_list_and_restore(store: ProjectStore, tmp_path: Path) -> None:
    pid = store.create_project("T2", "").id
    store.save_messages(
        pid,
        [{"role": "user", "content": "first line", "created_at": "2026-02-01T10:00:00"}],
    )
    sid = store.archive_active_conversation_and_clear(pid)
    assert sid
    assert store.load_messages(pid) == []
    items = store.list_modeling_conversation_history(pid)
    assert len(items) == 1
    assert items[0]["id"] == sid
    assert "first" in (items[0]["preview"] or "")
    restored = store.restore_modeling_conversation(pid, sid)
    assert len(restored) == 1
    assert restored[0]["content"] == "first line"


def test_migrate_legacy_messages_json(store: ProjectStore, tmp_path: Path) -> None:
    pid = store.create_project("T3", "").id
    project = store.get_project(pid)
    ws = Path(project.workspace)
    d = Path(store.root) / pid
    legacy = [{"role": "user", "content": "legacy", "created_at": "2025-12-01T00:00:00"}]
    (d / "messages.json").write_text(
        json.dumps({"messages": legacy}, ensure_ascii=False),
        encoding="utf-8",
    )
    loaded = store.load_messages(pid)
    assert loaded == legacy
    assert (ws / "conversations" / "active.json").is_file()
