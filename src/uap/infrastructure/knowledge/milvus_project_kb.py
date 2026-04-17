"""
项目知识库：Milvus Lite 本地文件 + 每项目独立 collection，IVF_FLAT + COSINE。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

from pymilvus import DataType, MilvusClient
from pymilvus.milvus_client import IndexParams

from uap.config import UapConfig
from uap.infrastructure.llm.ollama_client import OllamaClient, OllamaConfig

_LOG = logging.getLogger("uap.knowledge")

# 与需求一致
INDEX_BUILD_PARAMS: dict[str, Any] = {
    "metric_type": "COSINE",
    "index_type": "IVF_FLAT",
    "params": {"nlist": 1264},
}

SEARCH_PARAMS: dict[str, Any] = {
    "metric_type": "COSINE",
    "params": {"nprobe": 32},
}

TEXT_MAX_LEN = 65000
CHUNK_SIZE = 900
CHUNK_OVERLAP = 120
MAX_FILE_BYTES = 32 * 1024 * 1024


def _milvus_uri(cfg: UapConfig) -> str:
    raw = (cfg.storage.milvus_lite_path or "").strip()
    if raw:
        p = Path(raw).expanduser()
    else:
        p = Path.home() / ".uap" / "milvus_lite.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p.resolve())


def collection_name(project_id: str) -> str:
    """Milvus 集合名：字母数字下划线，长度受限。"""
    safe = re.sub(r"[^0-9a-zA-Z]+", "_", project_id).strip("_")
    if not safe:
        safe = "p"
    name = f"kb_{safe}"[:240]
    return name


def _chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


def _read_plain_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in (".txt", ".md", ".markdown"):
        raise ValueError(f"当前仅支持 .txt / .md 文件，收到: {suffix}")
    raw = path.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError(f"文件过大（>{MAX_FILE_BYTES // (1024 * 1024)}MB）")
    return raw.decode("utf-8", errors="replace")


class ProjectKnowledgeService:
    """按项目维护 Milvus Lite collection 与文档块。"""

    def __init__(self, config: UapConfig):
        self._config = config
        self._client: Optional[MilvusClient] = None
        self._ollama: Optional[OllamaClient] = None

    def reset_clients(self) -> None:
        """配置变更后丢弃缓存连接（维度/模型/路径变化）。"""
        if self._ollama is not None:
            try:
                self._ollama.close()
            except Exception:
                pass
            self._ollama = None
        try:
            if self._client is not None:
                self._client.close()
        except Exception:
            pass
        self._client = None

    def _get_client(self) -> MilvusClient:
        if self._client is None:
            try:
                self._client = MilvusClient(uri=_milvus_uri(self._config))
            except Exception as e:
                _LOG.exception("Milvus Lite 连接失败")
                raise RuntimeError(
                    "无法连接 Milvus Lite。请安装: pip install 'pymilvus[milvus_lite]>=2.4.0' "
                    "并使用 Python 3.10–3.12（部分平台对 milvus-lite 有版本限制）。"
                ) from e
        return self._client

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

    def _build_schema(self, dim: int) -> Any:
        schema = MilvusClient.create_schema(enable_dynamic_field=False)
        schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field("project_id", DataType.VARCHAR, max_length=128)
        schema.add_field("source_name", DataType.VARCHAR, max_length=512)
        schema.add_field("chunk_index", DataType.INT64)
        schema.add_field("text", DataType.VARCHAR, max_length=TEXT_MAX_LEN)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dim)
        return schema

    def ensure_collection(self, project_id: str) -> dict[str, Any]:
        """创建空集合并建立 IVF_FLAT 索引后 load（若已存在则跳过创建）。"""
        name = collection_name(project_id)
        cli = self._get_client()
        dim = int(self._config.embedding.dimension)

        if cli.has_collection(name):
            try:
                cli.load_collection(name)
            except Exception:
                _LOG.debug("load_collection %s (may already loaded)", name)
            return {"ok": True, "collection": name, "created": False}

        schema = self._build_schema(dim)
        cli.create_collection(collection_name=name, schema=schema, index_params=None)

        ip = IndexParams()
        ip.add_index(
            field_name="vector",
            index_type=INDEX_BUILD_PARAMS["index_type"],
            index_name="vec_ivf",
            metric_type=INDEX_BUILD_PARAMS["metric_type"],
            params=INDEX_BUILD_PARAMS["params"],
        )
        cli.create_index(collection_name=name, index_params=ip)
        cli.load_collection(name)
        return {"ok": True, "collection": name, "created": True}

    def status(self, project_id: str) -> dict[str, Any]:
        name = collection_name(project_id)
        cli = self._get_client()
        if not cli.has_collection(name):
            return {"ok": True, "exists": False, "collection": name, "row_count": 0}
        try:
            cli.load_collection(name)
        except Exception:
            pass
        stats = cli.get_collection_stats(name)
        rows = int(stats.get("row_count", 0))
        return {"ok": True, "exists": True, "collection": name, "row_count": rows}

    def import_file(self, project_id: str, file_path: str) -> dict[str, Any]:
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            return {"ok": False, "error": f"文件不存在: {path}"}

        self.ensure_collection(project_id)
        name = collection_name(project_id)
        cli = self._get_client()

        text = _read_plain_text(path)
        chunks = _chunk_text(text)
        if not chunks:
            return {"ok": False, "error": "文件无有效文本内容"}

        rows: list[dict[str, Any]] = []
        for i, ch in enumerate(chunks):
            vec = self._embed(ch)
            piece = ch[:TEXT_MAX_LEN]
            rows.append(
                {
                    "project_id": project_id,
                    "source_name": path.name[:500],
                    "chunk_index": i,
                    "text": piece,
                    "vector": vec,
                }
            )

        cli.insert(collection_name=name, data=rows)
        try:
            cli.flush(name)
        except Exception:
            _LOG.debug("flush optional")

        return {
            "ok": True,
            "chunks": len(rows),
            "source_name": path.name,
            "collection": name,
        }

    def search(self, project_id: str, query: str, top_k: int = 5) -> dict[str, Any]:
        q = (query or "").strip()
        if not q:
            return {"ok": False, "error": "查询为空"}

        name = collection_name(project_id)
        cli = self._get_client()
        if not cli.has_collection(name):
            return {"ok": False, "error": "知识库不存在，请先初始化或导入文档"}

        try:
            cli.load_collection(name)
        except Exception:
            pass

        vec = self._embed(q)
        flt = f'project_id == "{project_id}"'
        res = cli.search(
            collection_name=name,
            data=[vec],
            filter=flt,
            limit=max(1, min(top_k, 50)),
            output_fields=["text", "source_name", "chunk_index"],
            search_params=SEARCH_PARAMS,
            anns_field="vector",
        )
        hits: list[dict[str, Any]] = []
        for group in res or []:
            for hit in group or []:
                ent = hit.get("entity") or {}
                hits.append(
                    {
                        "text": ent.get("text", ""),
                        "source_name": ent.get("source_name", ""),
                        "chunk_index": ent.get("chunk_index", 0),
                        "distance": hit.get("distance"),
                    }
                )
        return {"ok": True, "hits": hits}
