"""
项目知识库：Milvus（Lite 本地文件 或 独立服务如 Docker）+ 每项目独立 collection，IVF_FLAT + COSINE。
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Any, Optional

from pymilvus import DataType, MilvusClient
from pymilvus.milvus_client import IndexParams

from uap.adapters.llm.ollama_client import OllamaClient, OllamaConfig
from uap.settings import UapConfig

_LOG = logging.getLogger("uap.knowledge")


def _milvus_lite_import_ok() -> tuple[bool, str]:
    """
    本地 Milvus Lite（文件 URI）依赖 ``milvus_lite`` 包。

    注意：PyPI 上 **milvus-lite 长期未提供 Windows (win_amd64) 轮子**，
    因此在原生 Windows 上通常无法 ``pip install``，与是否执行
    ``pip install pymilvus[milvus_lite]`` 无关。
    """
    try:
        import milvus_lite  # noqa: F401

        return True, ""
    except ImportError:
        if sys.platform == "win32":
            return (
                False,
                "本地 Milvus Lite 在 Windows 上不可用：PyPI 的 milvus-lite 未提供 win_amd64 轮子，"
                "无法安装 milvus_lite 模块。可选：在 WSL2/Linux 下运行本应用；"
                "或在设置中将「Milvus 后端」改为「独立服务」并连接本机 Docker（如 http://127.0.0.1:19530）。"
                "知识库在仅使用 Lite 文件模式时于本机 Windows 上将处于停用状态。",
            )
        return (
            False,
            "未安装 milvus-lite。请执行: pip install 'pymilvus[milvus_lite]>=2.4.0'。"
            "若已安装仍失败，请确认 Python 版本与平台受 pymilvus / milvus-lite 支持。",
        )


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


def _milvus_lite_file_uri(cfg: UapConfig) -> str:
    raw = (cfg.storage.milvus_lite_path or "").strip()
    if raw:
        p = Path(raw).expanduser()
    else:
        p = Path.home() / ".uap" / "milvus_lite.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p.resolve())


def _milvus_standalone_http_uri(cfg: UapConfig) -> str:
    host = (cfg.storage.milvus_host or "localhost").strip() or "localhost"
    port = int(cfg.storage.milvus_port)
    scheme = "https" if cfg.storage.milvus_use_tls else "http"
    return f"{scheme}://{host}:{port}"


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
            cfg = self._config
            if cfg.storage.milvus_backend == "standalone":
                uri = _milvus_standalone_http_uri(cfg)
                tok = (cfg.storage.milvus_token or "").strip()
                kw: dict[str, Any] = {}
                if tok:
                    kw["token"] = tok
                try:
                    self._client = MilvusClient(uri=uri, **kw)
                except Exception as e:
                    _LOG.exception("Milvus 独立服务连接失败 uri=%s", uri)
                    raise RuntimeError(
                        f"无法连接 Milvus 独立服务（{uri}）。"
                        "请确认 Docker 已启动、端口已映射（常用 19530），且 pymilvus 版本与 Milvus 2.x 兼容。"
                    ) from e
            else:
                ok, err = _milvus_lite_import_ok()
                if not ok:
                    raise RuntimeError(err)
                try:
                    self._client = MilvusClient(uri=_milvus_lite_file_uri(cfg))
                except Exception as e:
                    _LOG.exception("Milvus Lite 连接失败")
                    raise RuntimeError(
                        "无法连接 Milvus Lite（已检测到 milvus_lite 可导入）。"
                        "请检查存储路径权限或 pymilvus 版本。"
                        "若使用本地文件 URI，通常仍需: pip install 'pymilvus[milvus_lite]>=2.4.0'。"
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
        try:
            cli = self._get_client()
        except RuntimeError as e:
            return {"ok": False, "collection": name, "kb_available": False, "error": str(e)}
        dim = int(self._config.embedding.dimension)

        if cli.has_collection(name):
            try:
                cli.load_collection(name)
            except Exception:
                _LOG.debug("load_collection %s (may already loaded)", name)
            return {"ok": True, "collection": name, "created": False, "kb_available": True}

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
        return {"ok": True, "collection": name, "created": True, "kb_available": True}

    def status(self, project_id: str) -> dict[str, Any]:
        name = collection_name(project_id)
        try:
            cli = self._get_client()
        except RuntimeError as e:
            return {
                "ok": False,
                "kb_available": False,
                "exists": False,
                "collection": name,
                "row_count": 0,
                "error": str(e),
            }
        if not cli.has_collection(name):
            return {
                "ok": True,
                "kb_available": True,
                "exists": False,
                "collection": name,
                "row_count": 0,
            }
        try:
            cli.load_collection(name)
        except Exception:
            pass
        stats = cli.get_collection_stats(name)
        rows = int(stats.get("row_count", 0))
        return {
            "ok": True,
            "kb_available": True,
            "exists": True,
            "collection": name,
            "row_count": rows,
        }

    def import_file(self, project_id: str, file_path: str) -> dict[str, Any]:
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            return {"ok": False, "error": f"文件不存在: {path}"}

        ens = self.ensure_collection(project_id)
        if not ens.get("ok"):
            return {"ok": False, "error": ens.get("error") or "知识库不可用", "kb_available": False}
        name = collection_name(project_id)
        try:
            cli = self._get_client()
        except RuntimeError as e:
            return {"ok": False, "error": str(e), "kb_available": False}

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

    def ingest_truncation_fragments(self, project_id: str, fragments: list[dict[str, Any]]) -> None:
        """
        将上下文截断掉的尾部文本分块写入当前项目 collection（与文件导入共用 schema）。

        ``fragments`` 每项建议含 ``text``、``segment``、``session_id``、``llm_round``、``step_id``。
        """
        if not fragments:
            return
        pid = (project_id or "").strip()
        if not pid:
            return

        ens = self.ensure_collection(pid)
        if not ens.get("ok"):
            _LOG.warning("KB truncation ingest skipped: %s", ens.get("error"))
            return
        name = collection_name(pid)
        try:
            cli = self._get_client()
        except RuntimeError as e:
            _LOG.warning("KB truncation ingest skipped: %s", e)
            return
        rows: list[dict[str, Any]] = []
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
                rows.append(
                    {
                        "project_id": pid,
                        "source_name": src,
                        "chunk_index": row_idx,
                        "text": piece,
                        "vector": vec,
                    }
                )
                row_idx += 1

        if not rows:
            return
        cli.insert(collection_name=name, data=rows)
        try:
            cli.flush(name)
        except Exception:
            _LOG.debug("flush optional after truncation ingest")

    def search(self, project_id: str, query: str, top_k: int = 5) -> dict[str, Any]:
        q = (query or "").strip()
        if not q:
            return {"ok": False, "error": "查询为空"}

        name = collection_name(project_id)
        try:
            cli = self._get_client()
        except RuntimeError as e:
            return {"ok": False, "error": str(e), "kb_available": False, "hits": []}
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

    def ingest_snippets(
        self, project_id: str, snippets: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        将若干文本片段写入当前项目 collection（与文件导入共用 schema）。

        ``snippets`` 每项含 ``text``、``source_name``（≤512）；用于记忆抽取等。
        """
        rows_in = [x for x in (snippets or []) if isinstance(x, dict)]
        if not rows_in:
            return {"ok": True, "chunks": 0}

        ens = self.ensure_collection(project_id)
        if not ens.get("ok"):
            return {"ok": False, "error": ens.get("error") or "知识库不可用", "chunks": 0}
        name = collection_name(project_id)
        try:
            cli = self._get_client()
        except RuntimeError as e:
            return {"ok": False, "error": str(e), "chunks": 0}

        rows: list[dict[str, Any]] = []
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
                rows.append(
                    {
                        "project_id": project_id,
                        "source_name": f"{src}|c{row_idx}"[:512],
                        "chunk_index": row_idx,
                        "text": piece,
                        "vector": vec,
                    }
                )
                row_idx += 1

        if not rows:
            return {"ok": True, "chunks": 0}

        cli.insert(collection_name=name, data=rows)
        try:
            cli.flush(name)
        except Exception:
            _LOG.debug("flush optional after ingest_snippets")

        return {"ok": True, "chunks": len(rows), "collection": name}
