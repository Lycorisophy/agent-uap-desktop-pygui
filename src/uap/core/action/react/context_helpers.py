"""ReAct / 建模链路：将已有 ``SystemModel`` 压成短文本，注入对话上下文。"""

from __future__ import annotations

from typing import Any


def merge_react_extra_from_skill_result(
    extra_context: dict[str, Any],
    skill_id: str,
    result: dict[str, Any] | None,
) -> None:
    """
    将本轮已成功执行的结构化技能结果并入 ``extra_context["existing_model"]``，
    并刷新 ``extra_context["system_model"]`` 摘要，使后续 ``decide`` 轮次中的
    「当前项目已有模型摘要」与工具观察一致（避免 ``define_variable`` 已执行多
    次仍显示「变量: （尚未定义）」）。
    """
    if not isinstance(extra_context, dict) or not isinstance(result, dict):
        return
    changed = False
    em = extra_context.get("existing_model")
    if em is None:
        em = {}
        extra_context["existing_model"] = em
    if not isinstance(em, dict):
        return

    if skill_id == "define_variable":
        vd = result.get("variable")
        if isinstance(vd, dict):
            nm = (vd.get("name") or "").strip()
            if nm:
                kept = [
                    v
                    for v in (em.get("variables") or [])
                    if not isinstance(v, dict) or (v.get("name") or "").strip() != nm
                ]
                kept.append(vd)
                em["variables"] = kept
                changed = True
    elif skill_id == "discover_relations":
        rd = result.get("relation")
        if isinstance(rd, dict):
            rels = list(em.get("relations") or [])
            rid = (rd.get("id") or "").strip()
            if rid:
                rels = [r for r in rels if not isinstance(r, dict) or (r.get("id") or "").strip() != rid]
            rels.append(rd)
            em["relations"] = rels
            changed = True
    elif skill_id == "extract_model":
        vlist = result.get("variables")
        rlist = result.get("relations")
        if isinstance(vlist, list) and vlist and all(isinstance(x, dict) for x in vlist):
            em["variables"] = list(vlist)
            changed = True
        if isinstance(rlist, list) and rlist and all(isinstance(x, dict) for x in rlist):
            em["relations"] = list(rlist)
            changed = True

    if changed:
        extra_context["system_model"] = format_system_model_for_prompt(em)


def format_system_model_for_prompt(
    model: Any,
    *,
    max_description_len: int = 400,
    max_variable_names: int = 24,
    max_total_chars: int = 2500,
) -> str:
    """
    将 ``SystemModel`` 或 ``model_dump()`` 字典格式化为可读摘要，供 ``react_decision_user`` 使用。
    空模型返回空字符串。
    """
    if model is None:
        return ""
    if hasattr(model, "model_dump"):
        data = model.model_dump()
    elif isinstance(model, dict):
        data = model
    else:
        return ""

    variables = data.get("variables") or []
    relations = data.get("relations") or []
    constraints = data.get("constraints") or []
    if not variables and not relations and not constraints:
        name = (data.get("name") or "").strip()
        desc = (data.get("description") or "").strip()
        if not name and not desc:
            return ""

    lines: list[str] = ["【当前项目已有模型摘要】"]
    name = (data.get("name") or "").strip()
    if name:
        lines.append(f"名称: {name}")
    desc = (data.get("description") or "").strip()
    if desc:
        lines.append(f"描述: {desc[:max_description_len]}" + ("…" if len(desc) > max_description_len else ""))
    conf = data.get("confidence")
    if conf is not None:
        lines.append(f"整体置信度: {conf}")

    if variables:
        names: list[str] = []
        for v in variables[:max_variable_names]:
            if isinstance(v, dict):
                nm = (v.get("name") or "").strip() or "(未命名)"
                u = (v.get("unit") or "").strip()
                names.append(f"{nm}" + (f" ({u})" if u else ""))
            else:
                names.append(str(v))
        extra = len(variables) - max_variable_names
        tail = f" 等共 {len(variables)} 个" if extra > 0 else f" 共 {len(variables)} 个"
        lines.append("变量: " + "，".join(names) + tail)
    else:
        lines.append("变量: （尚未定义）")

    if relations:
        rel_lines: list[str] = []
        for r in relations[:12]:
            if not isinstance(r, dict):
                rel_lines.append(str(r))
                continue
            ev = (r.get("effect_var") or r.get("to_var") or "").strip()
            cv = r.get("cause_vars") or r.get("from_var")
            if isinstance(cv, list):
                src = "，".join(cv) if cv else ""
            elif cv:
                src = str(cv)
            else:
                src = ""
            expr = (r.get("expression") or "")[:80]
            bit = " → ".join(p for p in (src, ev) if p) or (r.get("name") or "关系")
            if expr:
                bit += f" ({expr}…)" if len(expr) >= 80 else f" ({expr})"
            rel_lines.append(bit)
        lines.append("关系: " + "；".join(rel_lines))
        if len(relations) > 12:
            lines.append(f"（另有关系 {len(relations) - 12} 条已省略）")

    if constraints:
        lines.append(f"约束: {len(constraints)} 条")

    out = "\n".join(lines)
    if len(out) > max_total_chars:
        return out[: max_total_chars - 1] + "…"
    return out
