"""项目知识库工具函数与配置回归（不依赖 Milvus Lite 运行时）。"""

from uap.config import UapConfig
from uap.infrastructure.knowledge.milvus_project_kb import (
    SEARCH_PARAMS,
    INDEX_BUILD_PARAMS,
    collection_name,
    _chunk_text,
)


def test_collection_name_sanitizes() -> None:
    assert collection_name("abc-123").startswith("kb_")


def test_chunk_text_overlap() -> None:
    t = "a" * 2000
    parts = _chunk_text(t, size=500, overlap=50)
    assert len(parts) >= 3
    assert all(len(p) <= 500 for p in parts)


def test_index_params_match_requirements() -> None:
    assert INDEX_BUILD_PARAMS["index_type"] == "IVF_FLAT"
    assert INDEX_BUILD_PARAMS["metric_type"] == "COSINE"
    assert INDEX_BUILD_PARAMS["params"]["nlist"] == 1264
    assert SEARCH_PARAMS["metric_type"] == "COSINE"
    assert SEARCH_PARAMS["params"]["nprobe"] == 32


def test_embedding_config_dimension_default() -> None:
    cfg = UapConfig()
    assert cfg.embedding.dimension == 4096
    assert cfg.embedding.model == "qwen3-embedding:8b"
