"""Milvus Lite 可用性说明（与平台相关）。"""

from uap.config import UapConfig
from uap.infrastructure.knowledge.milvus_project_kb import (
    _milvus_lite_import_ok,
    _milvus_standalone_http_uri,
)


def test_milvus_lite_import_check_returns_tuple() -> None:
    ok, msg = _milvus_lite_import_ok()
    assert isinstance(ok, bool)
    assert isinstance(msg, str)


def test_milvus_standalone_uri_http() -> None:
    cfg = UapConfig()
    cfg.storage.milvus_host = "127.0.0.1"
    cfg.storage.milvus_port = 19530
    cfg.storage.milvus_use_tls = False
    assert _milvus_standalone_http_uri(cfg) == "http://127.0.0.1:19530"


def test_milvus_standalone_uri_https() -> None:
    cfg = UapConfig()
    cfg.storage.milvus_use_tls = True
    assert _milvus_standalone_http_uri(cfg).startswith("https://")
