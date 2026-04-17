"""
将 ``SystemModel`` 投影为轻量实体关系图（JSON 落盘用）。

不依赖外部图数据库；边主要来自 ``Relation.cause_vars`` → ``effect_var``。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from uap.project.models import SystemModel


def build_entity_graph_payload(project_id: str, model: SystemModel) -> dict[str, Any]:
    """
    构建可序列化的图载荷（version=1）。

    - 节点：变量名（``Variable.name``），以及边中出现的、尚未声明的变量名（补全端点）。
    - 边：每个 ``cause_vars`` 元素指向 ``effect_var``（有向）；``cause_vars`` 为空时不生成边。
    """
    pid = (project_id or "").strip() or "unknown"
    nodes_by_id: dict[str, dict[str, Any]] = {}

    def _ensure_var_node(name: str) -> None:
        n = (name or "").strip()
        if not n:
            return
        nid = f"var:{n}"
        if nid not in nodes_by_id:
            nodes_by_id[nid] = {"id": nid, "name": n, "type": "variable"}

    for v in model.variables or []:
        _ensure_var_node(getattr(v, "name", None) or "")

    edges: list[dict[str, Any]] = []
    ei = 0
    for rel in model.relations or []:
        effect = (getattr(rel, "effect_var", None) or "").strip()
        causes = [
            str(c).strip()
            for c in (getattr(rel, "cause_vars", None) or [])
            if str(c).strip()
        ]
        rname = (getattr(rel, "name", None) or getattr(rel, "id", None) or "relation") or "relation"
        rt = getattr(rel, "relation_type", "equation")
        rtype = rt.value if hasattr(rt, "value") else str(rt)
        if not effect or not causes:
            continue
        _ensure_var_node(effect)
        for c in causes:
            _ensure_var_node(c)
            src, tgt = f"var:{c}", f"var:{effect}"
            edges.append(
                {
                    "id": f"edge_{ei}",
                    "source": src,
                    "target": tgt,
                    "relation_type": str(rtype)[:64],
                    "relation_name": str(rname)[:200],
                }
            )
            ei += 1

    nodes = list(nodes_by_id.values())
    cc = len(model.constraints or [])

    return {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "project_id": pid,
        "model_name": (model.name or "")[:500],
        "nodes": nodes,
        "edges": edges,
        "constraints_count": cc,
    }
