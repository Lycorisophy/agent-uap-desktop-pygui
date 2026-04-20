"""
项目知识库：SQLite 存 float32 向量 + 余弦 Top-K（本机免 Milvus）。

与 ``milvus_project_kb.ProjectKnowledgeService`` 对外方法对齐，供工厂按配置择一。
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Optional

import numpy as np

from uap.adapters.llm.ollama_client import OllamaClient, OllamaConfig
from uap.core.memory.knowledge.milvus_project_kb import (
    MAX_FILE_BYTES,
    TEXT_MAX_LEN,
    _chunk_text,
    _read_plain_text,
    collection_name,
)
from uap.settings import UapConfig

_LOG = logging.getLogger("uap.knowledge.sqlite")


def _sqlite_db_path(cfg: UapConfig) -> Path:
    raw = (cfg.storage.sqlite_vec_path or "").strip()
    if raw:
        p = Path(raw).expanduser()
    else:
        p = Path.home() / ".uap" / "kb_vec.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p.resolve()


def _vec_to_blob(vec: list[float]) -> bytes:
    arr = np.asarray(vec, dtype=np.float32)
    return arr.tobytes()


def _blob_to_vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def _cosine_distance(q: np.ndarray, v: np.ndarray) -> float:
    """与 Milvus COSINE 语义对齐：距离越小越相似（1 - cosine_similarity）。"""
    qn = float(np.linalg.norm(q))
    vn = float(np.linalg.norm(v))
    if qn < 1e-12 or vn < 1e-12:
        return 1.0
    sim = float(np.dot(q, v) / (qn * vn))
    sim = max(-1.0, min(1.0, sim))
    return 1.0 - sim


class SqliteVecProjectKnowledgeService:
    """单库多项目：``kb_chunks`` 表按 ``project_id`` 过滤。"""

    def __init__(self, config: UapConfig):
        self._config = config
        self._ollama: Optional[OllamaClient] = None
        self._conn: Optional[sqlite3.Connection] = None

    def reset_clients(self) -> None:
        if self._ollama is not None:
            try:
                self._ollama.close()
            except Exception:
                pass
            self._ollama = None
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _db_path(self) -> Path:
        return _sqlite_db_path(self._config)

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            path = self._db_path()
            self._conn = sqlite3.connect(str(path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._ensure_schema(self._conn)
        return self._conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kb_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                source_name TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                dim INTEGER NOT NULL,
                embedding BLOB NOT NULL,
                UNIQUE(project_id, source_name, chunk_index)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_kb_chunks_project ON kb_chunks(project_id)"
        )
        conn.commit()

    def _get_ollama(self) -> OllamaClient:
        if self._ollama is None:
            base = (self._config.embedding.base_url or "").strip() or self._config.llm.base_url
            self._ollama = OllamaClient(
                OllamaConfig(
                    base_url=base,
                    embedding_model=self._config.embedding.model,
                    timeout=120,
                )
            )
        return self._ollama

    def _embed(self, text: str) -> list[float]:
        o = self._get_ollama()
        vec = o.create_embedding(text, model=self._config.embedding.model)
        if not vec:
            raise RuntimeError("嵌入为空：请确认 Ollama 已启动且已拉取嵌入模型。")
        dim_cfg = int(self._config.embedding.dimension)
        if len(vec) != dim_cfg:
            raise ValueError(
                f"嵌入维度 {len(vec)} 与配置 embedding.dimension={dim_cfg} 不一致，请修改设置。"
            )
        return vec

    def ensure_collection(self, project_id: str) -> dict[str, Any]:
        name = collection_name(project_id)
        try:
            conn = self._get_conn()
        except OSError as e:
            return {"ok": False, "collection": name, "kb_available": False, "error": str(e)}
        dim = int(self._config.embedding.dimension)
        cur = conn.execute(
            "SELECT COUNT(*) AS c FROM kb_chunks WHERE project_id = ?",
            (project_id,),
        )
        row = cur.fetchone()
        n = int(row["c"]) if row else 0
        return {
            "ok": True,
            "collection": name,
            "created": n == 0,
            "kb_available": True,
            "backend": "sqlite_vec",
            "dim": dim,
        }

    def status(self, project_id: str) -> dict[str, Any]:
        name = collection_name(project_id)
        try:
            conn = self._get_conn()
        except OSError as e:
            return {
                "ok": False,
                "kb_available": False,
                "exists": False,
                "collection": name,
                "row_count": 0,
                "error": str(e),
                "backend": "sqlite_vec",
            }
        cur = conn.execute(
            "SELECT COUNT(*) AS c FROM kb_chunks WHERE project_id = ?",
            (project_id,),
        )
        row = cur.fetchone()
        rows = int(row["c"]) if row else 0
        return {
            "ok": True,
            "kb_available": True,
            "exists": rows > 0,
            "collection": name,
            "row_count": rows,
            "backend": "sqlite_vec",
        }

    def import_file(self, project_id: str, file_path: str) -> dict[str, Any]:
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            return {"ok": False, "error": f"文件不存在: {path}"}

        ens = self.ensure_collection(project_id)
        if not ens.get("ok"):
            return {"ok": False, "error": ens.get("error") or "知识库不可用", "kb_available": False}
        name = collection_name(project_id)
        conn = self._get_conn()
        text = _read_plain_text(path)
        chunks = _chunk_text(text)
        if not chunks:
            return {"ok": False, "error": "文件无有效文本内容"}

        dim = int(self._config.embedding.dimension)
        rows_data: list[tuple[Any, ...]] = []
        for i, ch in enumerate(chunks):
            vec = self._embed(ch)
            piece = ch[:TEXT_MAX_LEN]
            blob = _vec_to_blob(vec)
            rows_data.append((project_id, path.name[:500], i, piece, dim, blob))

        conn.executemany(
            """
            INSERT INTO kb_chunks (project_id, source_name, chunk_index, text, dim, embedding)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, source_name, chunk_index) DO UPDATE SET
                text = excluded.text,
                dim = excluded.dim,
                embedding = excluded.embedding
            """,
            rows_data,
        )
        conn.commit()
        return {
            "ok": True,
            "chunks": len(rows_data),
            "source_name": path.name,
            "collection": name,
            "backend": "sqlite_vec",
        }

    def ingest_truncation_fragments(self, project_id: str, fragments: list[dict[str, Any]]) -> None:
        if not fragments:
            return
        pid = (project_id or "").strip()
        if not pid:
            return

        ens = self.ensure_collection(pid)
        if not ens.get("ok"):
            _LOG.warning("KB truncation ingest skipped: %s", ens.get("error"))
            return
        conn = self._get_conn()
        dim = int(self._config.embedding.dimension)
        rows_data: list[tuple[Any, ...]] = []
        row_idx = 0

        for frag in fragments:
            raw = (frag.get("text") or "").strip()
            if not raw:
                continue
            meta = f"seg={frag.get('segment','')}|r={frag.get('llm_round','')}|step={frag.get('step_id','')}"
            sid = str(frag.get("session_id") or "")[:80]
            base_src = f"uap_trunc|{sid}|{meta}"[:500]
            prefixed = "[UAP:context_truncation]\n" + raw
            chunks = _chunk_text(prefixed)
            for ch in chunks:
                vec = self._embed(ch)
                piece = ch[:TEXT_MAX_LEN]
                src = f"{base_src}|c{row_idx}"[:512]
                blob = _vec_to_blob(vec)
                rows_data.append((pid, src, row_idx, piece, dim, blob))
                row_idx += 1

        if not rows_data:
            return
        conn.executemany(
            """
            INSERT INTO kb_chunks (project_id, source_name, chunk_index, text, dim, embedding)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, source_name, chunk_index) DO UPDATE SET
                text = excluded.text,
                dim = excluded.dim,
                embedding = excluded.embedding
            """,
            rows_data,
        )
        conn.commit()

    def search(self, project_id: str, query: str, top_k: int = 5) -> dict[str, Any]:
        q = (query or "").strip()
        if not q:
            return {"ok": False, "error": "查询为空"}

        name = collection_name(project_id)
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT source_name, chunk_index, text, embedding FROM kb_chunks WHERE project_id = ?",
            (project_id,),
        )
        all_rows = cur.fetchall()
        if not all_rows:
            return {"ok": False, "error": "知识库不存在，请先初始化或导入文档"}

        qvec = np.asarray(self._embed(q), dtype=np.float32)
        lim = max(1, min(top_k, 50))
        scored: list[tuple[float, sqlite3.Row]] = []
        for r in all_rows:
            v = _blob_to_vec(bytes(r["embedding"]))
            if v.shape[0] != qvec.shape[0]:
                continue
            d = _cosine_distance(qvec, v)
            scored.append((d, r))
        scored.sort(key=lambda x: x[0])
        hits: list[dict[str, Any]] = []
        for d, r in scored[:lim]:
            hits.append(
                {
                    "text": r["text"] or "",
                    "source_name": r["source_name"] or "",
                    "chunk_index": int(r["chunk_index"] or 0),
                    "distance": float(d),
                }
            )
        return {"ok": True, "hits": hits, "backend": "sqlite_vec"}

    def ingest_snippets(self, project_id: str, snippets: list[dict[str, Any]]) -> dict[str, Any]:
        rows_in = [x for x in (snippets or []) if isinstance(x, dict)]
        if not rows_in:
            return {"ok": True, "chunks": 0}

        ens = self.ensure_collection(project_id)
        if not ens.get("ok"):
            return {"ok": False, "error": ens.get("error") or "知识库不可用", "chunks": 0}
        conn = self._get_conn()
        dim = int(self._config.embedding.dimension)
        rows_data: list[tuple[Any, ...]] = []
        row_idx = 0
        for sn in rows_in:
            raw = (sn.get("text") or "").strip()
            if not raw:
                continue
            src = (sn.get("source_name") or "agent_mem|snippet")[:512]
            chunks = _chunk_text(raw)
            for ch in chunks:
                vec = self._embed(ch)
                piece = ch[:TEXT_MAX_LEN]
                blob = _vec_to_blob(vec)
                sname = f"{src}|c{row_idx}"[:512]
                rows_data.append((project_id, sname, row_idx, piece, dim, blob))
                row_idx += 1

        if not rows_data:
            return {"ok": True, "chunks": 0}

        conn.executemany(
            """
            INSERT INTO kb_chunks (project_id, source_name, chunk_index, text, dim, embedding)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, source_name, chunk_index) DO UPDATE SET
                text = excluded.text,
                dim = excluded.dim,
                embedding = excluded.embedding
            """,
            rows_data,
        )
        conn.commit()
        name = collection_name(project_id)
        return {"ok": True, "chunks": len(rows_data), "collection": name, "backend": "sqlite_vec"}
