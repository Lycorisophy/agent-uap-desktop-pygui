"""
Episode 与抽取进度的 SQLite 持久化（与 ``_uap_index/cards.sqlite`` 同目录）。
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

_LOG = logging.getLogger("uap.core.memory.agent_memory")

SCHEMA_VERSION = 1


def agent_memory_db_path(projects_root: Path | str) -> Path:
    root = Path(projects_root)
    idx = root / "_uap_index"
    idx.mkdir(parents=True, exist_ok=True)
    return idx / "agent_memory.sqlite"


class AgentMemoryPersistence:
    """Episode 表 + extraction_progress 表。"""

    def __init__(self, db_path: Union[Path, str, None]) -> None:
        if db_path is None:
            self._db_path: Union[Path, str, None] = None
            self._memory_uri: str | None = None
        elif isinstance(db_path, str) and db_path.strip() == ":memory:":
            # 同一实例上多次 connect 需共享内存库，否则每次均为空库
            self._db_path = ":memory:"
            self._memory_uri = f"file:uap_am_{uuid.uuid4().hex}?mode=memory&cache=shared"
        else:
            self._db_path = Path(db_path)
            self._memory_uri = None

    @property
    def enabled(self) -> bool:
        return self._db_path is not None

    def _connect(self) -> sqlite3.Connection:
        assert self._db_path is not None
        if self._db_path == ":memory:":
            assert self._memory_uri is not None
            conn = sqlite3.connect(self._memory_uri, uri=True)
        else:
            assert isinstance(self._db_path, Path)
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        cur = conn.execute("PRAGMA user_version")
        ver = cur.fetchone()[0]
        if ver < SCHEMA_VERSION:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    processed INTEGER NOT NULL DEFAULT 0,
                    processed_at TEXT,
                    ref TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_episodes_project ON episodes(project_id);
                CREATE INDEX IF NOT EXISTS idx_episodes_processed ON episodes(project_id, processed);

                CREATE TABLE IF NOT EXISTS extraction_progress (
                    project_id TEXT PRIMARY KEY,
                    last_episode_id TEXT,
                    last_processed_at TEXT,
                    total_episodes_processed INTEGER NOT NULL DEFAULT 0,
                    extractor_version TEXT NOT NULL DEFAULT '1',
                    updated_at TEXT
                );
                """
            )
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()

    def insert_episode(
        self,
        project_id: str,
        content: str,
        *,
        source_type: str = "chat",
        ref: str | None = None,
    ) -> str | None:
        if not self.enabled:
            return None
        pid = (project_id or "").strip()
        text = (content or "").strip()
        if not pid or not text:
            return None
        eid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                conn.execute(
                    """
                    INSERT INTO episodes (id, project_id, source_type, content, created_at, processed, ref)
                    VALUES (?, ?, ?, ?, ?, 0, ?)
                    """,
                    (eid, pid, source_type[:64], text[:120000], now, ref),
                )
                conn.commit()
        except Exception:
            _LOG.exception("[AgentMemory] insert_episode failed project=%s", pid)
            return None
        return eid

    def list_unprocessed(self, project_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        pid = (project_id or "").strip()
        if not pid:
            return []
        limit = max(1, min(500, int(limit)))
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                cur = conn.execute(
                    """
                    SELECT id, project_id, source_type, content, created_at, processed, ref
                    FROM episodes
                    WHERE project_id = ? AND processed = 0
                    ORDER BY created_at ASC
                    LIMIT ?
                    """,
                    (pid, limit),
                )
                return [dict(row) for row in cur.fetchall()]
        except Exception:
            _LOG.exception("[AgentMemory] list_unprocessed failed")
            return []

    def mark_episode_processed(self, episode_id: str) -> None:
        if not self.enabled:
            return
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                conn.execute(
                    "UPDATE episodes SET processed = 1, processed_at = ? WHERE id = ?",
                    (now, episode_id),
                )
                conn.commit()
        except Exception:
            _LOG.exception("[AgentMemory] mark_episode_processed failed")

    def bump_progress(
        self,
        project_id: str,
        *,
        last_episode_id: str | None,
        delta_processed: int = 1,
        extractor_version: str = "1",
    ) -> None:
        if not self.enabled:
            return
        pid = (project_id or "").strip()
        if not pid:
            return
        now = datetime.now(timezone.utc).isoformat()
        d = max(0, int(delta_processed))
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                conn.execute(
                    """
                    INSERT INTO extraction_progress (
                        project_id, last_episode_id, last_processed_at,
                        total_episodes_processed, extractor_version, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project_id) DO UPDATE SET
                        last_episode_id = excluded.last_episode_id,
                        last_processed_at = excluded.last_processed_at,
                        total_episodes_processed = extraction_progress.total_episodes_processed + ?,
                        extractor_version = excluded.extractor_version,
                        updated_at = excluded.updated_at
                    """,
                    (pid, last_episode_id, now, d, extractor_version, now, d),
                )
                conn.commit()
        except Exception:
            _LOG.exception("[AgentMemory] bump_progress failed")

    def stats(self, project_id: str) -> dict[str, Any]:
        """供 UI：Episode 计数与进度摘要。"""
        if not self.enabled:
            return {"ok": False, "enabled": False}
        pid = (project_id or "").strip()
        if not pid:
            return {"ok": False, "error": "no_project"}
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                total = conn.execute(
                    "SELECT COUNT(*) FROM episodes WHERE project_id = ?", (pid,)
                ).fetchone()[0]
                pending = conn.execute(
                    "SELECT COUNT(*) FROM episodes WHERE project_id = ? AND processed = 0",
                    (pid,),
                ).fetchone()[0]
                row = conn.execute(
                    "SELECT * FROM extraction_progress WHERE project_id = ?", (pid,)
                ).fetchone()
                prog = dict(row) if row else None
            return {
                "ok": True,
                "enabled": True,
                "episode_total": int(total),
                "episode_pending": int(pending),
                "progress": prog,
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "enabled": True}
