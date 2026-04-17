"""实体关系图 JSON（B.3）与 ProjectStore 往返。"""

from pathlib import Path

from uap.application.project_service import ProjectService
from uap.config import MemoryConfig, UapConfig
from uap.infrastructure.persistence.project_store import ProjectStore
from uap.project.entity_graph import build_entity_graph_payload
from uap.project.models import Relation, SystemModel, Variable


def test_build_entity_graph_payload_edges_from_causes() -> None:
    m = SystemModel(
        name="t",
        variables=[
            Variable(name="a", description="", value_type="float", unit=""),
            Variable(name="b", description="", value_type="float", unit=""),
        ],
        relations=[
            Relation(
                name="r1",
                cause_vars=["a"],
                effect_var="b",
                relation_type="causal",
            )
        ],
    )
    p = build_entity_graph_payload("proj_x", m)
    assert p["version"] == 1
    assert p["project_id"] == "proj_x"
    assert len(p["nodes"]) == 2
    assert len(p["edges"]) == 1
    assert p["edges"][0]["source"] == "var:a"
    assert p["edges"][0]["target"] == "var:b"


def test_build_entity_graph_two_causes_two_edges() -> None:
    m = SystemModel(
        name="t",
        variables=[
            Variable(name="x", description="", value_type="float", unit=""),
            Variable(name="y", description="", value_type="float", unit=""),
            Variable(name="z", description="", value_type="float", unit=""),
        ],
        relations=[
            Relation(
                name="multi",
                cause_vars=["x", "y"],
                effect_var="z",
                relation_type="causal",
            )
        ],
    )
    p = build_entity_graph_payload("p", m)
    assert len(p["edges"]) == 2


def test_project_store_entity_graph_roundtrip(tmp_path: Path) -> None:
    store = ProjectStore(str(tmp_path))
    payload = {
        "version": 1,
        "project_id": "abc",
        "nodes": [{"id": "var:a", "name": "a", "type": "variable"}],
        "edges": [],
    }
    store.save_entity_graph("abc", payload)
    p = store.load_entity_graph("abc")
    assert p is not None
    assert p["project_id"] == "abc"
    assert len(p["nodes"]) == 1


def test_sync_entity_graph_skipped_when_disabled(tmp_path: Path) -> None:
    store = ProjectStore(str(tmp_path))
    cfg = UapConfig()
    cfg.memory = MemoryConfig(graph_enabled=False)
    ps = ProjectService(store, cfg)
    m = SystemModel(
        name="m",
        variables=[Variable(name="v", description="", value_type="float", unit="")],
    )
    ps._sync_entity_graph_if_enabled("pid", m)
    assert not (tmp_path / "pid" / store.ENTITY_GRAPH_FILE).exists()


def test_sync_entity_graph_writes_when_enabled(tmp_path: Path) -> None:
    store = ProjectStore(str(tmp_path))
    cfg = UapConfig()
    cfg.memory = MemoryConfig(graph_enabled=True)
    ps = ProjectService(store, cfg)
    m = SystemModel(
        name="m",
        variables=[Variable(name="v", description="", value_type="float", unit="")],
    )
    ps._sync_entity_graph_if_enabled("pid2", m)
    fp = tmp_path / "pid2" / store.ENTITY_GRAPH_FILE
    assert fp.is_file()
    loaded = store.load_entity_graph("pid2")
    assert loaded and loaded.get("project_id") == "pid2"
