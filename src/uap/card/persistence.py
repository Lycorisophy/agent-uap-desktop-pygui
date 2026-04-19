"""
卡片 SQLite 持久化（与 ProjectStore 文件库并存，按 projects_root 下 _uap_index/cards.sqlite）。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from uap.card.models import ConfirmationCard

_LOG = logging.getLogger("uap.card.persistence")

SCHEMA_VERSION = 1


class CardPersistence:
    """ConfirmationCard 生命周期落库；可选禁用（db_path 为 None）。"""

    def __init__(self, db_path: Path | str | None) -> None:
        self._db_path: Optional[Path] = Path(db_path) if db_path else None

    @property
    def enabled(self) -> bool:
        return self._db_path is not None

    def _connect(self) -> sqlite3.Connection:
        assert self._db_path is not None
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
                CREATE TABLE IF NOT EXISTS cards (
                    card_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    card_type TEXT NOT NULL,
                    title TEXT,
                    content TEXT,
                    options_json TEXT,
                    context_json TEXT,
                    status TEXT NOT NULL,
                    selected_option_id TEXT,
                    response_metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    responded_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_cards_project_id ON cards(project_id);
                CREATE INDEX IF NOT EXISTS idx_cards_status ON cards(status);
                CREATE INDEX IF NOT EXISTS idx_cards_created_at ON cards(created_at);
                """
            )
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()

    def insert_pending(self, card: ConfirmationCard) -> None:
        if not self.enabled:
            return
        project_id = str((card.context or {}).get("project_id") or "")
        options_json = json.dumps([o.to_dict() for o in card.options], ensure_ascii=False)
        context_json = json.dumps(dict(card.context or {}), ensure_ascii=False)
        ct = card.card_type.value if hasattr(card.card_type, "value") else str(card.card_type)
        created = card.created_at.isoformat() if isinstance(card.created_at, datetime) else str(card.created_at)
        exp = card.expires_at.isoformat() if card.expires_at else None
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                conn.execute(
                    """
                    INSERT INTO cards (
                        card_id, project_id, card_type, title, content,
                        options_json, context_json, status,
                        selected_option_id, response_metadata_json,
                        created_at, expires_at, responded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', NULL, NULL, ?, ?, NULL)
                    """,
                    (
                        card.card_id,
                        project_id,
                        ct,
                        card.title or "",
                        card.content or "",
                        options_json,
                        context_json,
                        created,
                        exp,
                    ),
                )
                conn.commit()
        except OSError as e:
            _LOG.error("[CardPersistence] insert_pending failed: %s", e)
        except sqlite3.IntegrityError:
            _LOG.debug("[CardPersistence] insert_pending duplicate card_id=%s", card.card_id)
        except sqlite3.Error as e:
            _LOG.error("[CardPersistence] insert_pending sqlite: %s", e)

    def update_responded(
        self,
        card_id: str,
        selected_option_id: str,
        metadata: dict[str, Any],
        responded_at: datetime,
    ) -> None:
        if not self.enabled:
            return
        status = "dismissed" if selected_option_id == "dismissed" else "responded"
        meta_json = json.dumps(dict(metadata or {}), ensure_ascii=False)
        ts = responded_at.isoformat() if isinstance(responded_at, datetime) else str(responded_at)
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                conn.execute(
                    """
                    UPDATE cards SET
                        status = ?,
                        selected_option_id = ?,
                        response_metadata_json = ?,
                        responded_at = ?
                    WHERE card_id = ?
                    """,
                    (status, selected_option_id, meta_json, ts, card_id),
                )
                conn.commit()
        except OSError as e:
            _LOG.error("[CardPersistence] update_responded failed: %s", e)
        except sqlite3.Error as e:
            _LOG.error("[CardPersistence] update_responded sqlite: %s", e)

    def update_status_expired(self, card_id: str) -> None:
        if not self.enabled:
            return
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                conn.execute(
                    "UPDATE cards SET status = 'expired' WHERE card_id = ?",
                    (card_id,),
                )
                conn.commit()
        except OSError as e:
            _LOG.error("[CardPersistence] update_status_expired failed: %s", e)
        except sqlite3.Error as e:
            _LOG.error("[CardPersistence] update_status_expired sqlite: %s", e)

    def list_by_project(self, project_id: str, limit: int = 50) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                cur = conn.execute(
                    """
                    SELECT * FROM cards
                    WHERE project_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (str(project_id), int(limit)),
                )
                rows = cur.fetchall()
        except (OSError, sqlite3.Error) as e:
            _LOG.error("[CardPersistence] list_by_project failed: %s", e)
            return []
        out: list[dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            try:
                d["options"] = json.loads(d.pop("options_json") or "[]")
            except json.JSONDecodeError:
                d["options"] = []
            try:
                d["context"] = json.loads(d.pop("context_json") or "{}")
            except json.JSONDecodeError:
                d["context"] = {}
            meta_raw = d.pop("response_metadata_json", None)
            try:
                d["response_metadata"] = json.loads(meta_raw) if meta_raw else {}
            except json.JSONDecodeError:
                d["response_metadata"] = {}
            out.append(d)
        return out
