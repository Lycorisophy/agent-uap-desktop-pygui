"""
ReAct 上下文压缩：预算检测、遮盖、删除、分级摘要、截断占位与异步入库。
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage

from uap.config import ContextCompressionConfig
from uap.prompts import PromptId, load_raw

_LOG = logging.getLogger("uap.react.context_compression")

_PLACEHOLDER_ORDER = (
    "task",
    "system_model",
    "dst_summary",
    "skills_desc",
    "trajectory",
)


def _unescape_braces_for_rendered_literals(fragment: str) -> str:
    """与 ``str.format`` 后一致：模板资产中的 ``{{`` / ``}}`` 在最终提示中变为单花括号。"""
    return fragment.replace("{{", "{").replace("}}", "}")


@lru_cache(maxsize=1)
def react_decision_template_literal_parts() -> tuple[str, ...]:
    """按占位符切分 ``react_decision_user.md``，得到 6 段静态字面量（含首尾说明）。"""
    tpl = load_raw(PromptId.REACT_DECISION_USER)
    literals: list[str] = []
    pos = 0
    for key in _PLACEHOLDER_ORDER:
        token = "{" + key + "}"
        idx = tpl.find(token, pos)
        if idx < 0:
            raise ValueError(f"react_decision_user 模板缺少占位符 {token!r}")
        literals.append(_unescape_braces_for_rendered_literals(tpl[pos:idx]))
        pos = idx + len(token)
    literals.append(_unescape_braces_for_rendered_literals(tpl[pos:]))
    return tuple(literals)


@dataclass
class ReactContextParts:
    """与 ``react_decision_user.md`` 占位符一一对应的可压缩片段。"""

    literal_pre: str
    literal_after_task: str
    literal_after_system_model: str
    literal_after_dst: str
    literal_after_skills: str
    literal_post: str
    task: str = ""
    system_model: str = ""
    dst_summary: str = ""
    skills_desc: str = ""
    trajectory: str = ""

    def clone(self) -> ReactContextParts:
        return ReactContextParts(
            literal_pre=self.literal_pre,
            literal_after_task=self.literal_after_task,
            literal_after_system_model=self.literal_after_system_model,
            literal_after_dst=self.literal_after_dst,
            literal_after_skills=self.literal_after_skills,
            literal_post=self.literal_post,
            task=self.task,
            system_model=self.system_model,
            dst_summary=self.dst_summary,
            skills_desc=self.skills_desc,
            trajectory=self.trajectory,
        )


def estimate_tokens(text: str) -> int:
    """粗算 token（无分词器时与 Ollama 场景兼容）。"""
    if not text:
        return 0
    n = len(text)
    return max(1, (n + 3) // 4)


def render_parts(p: ReactContextParts) -> str:
    return (
        p.literal_pre
        + p.task
        + p.literal_after_task
        + p.system_model
        + p.literal_after_system_model
        + p.dst_summary
        + p.literal_after_dst
        + p.skills_desc
        + p.literal_after_skills
        + p.trajectory
        + p.literal_post
    )


def total_estimate_tokens(p: ReactContextParts) -> int:
    return estimate_tokens(render_parts(p))


def _collapse_blank_lines(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


_RE_BASE64 = re.compile(r"[A-Za-z0-9+/]{80,}={0,2}")
_RE_BEARER = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|authorization)\s*[:=]\s*[^\s\n]{8,}"
)
_RE_URL = re.compile(r"https?://[^\s]{120,}")


def redact_sensitive(text: str, cfg: ContextCompressionConfig) -> str:
    if not cfg.enable_redaction or not text:
        return text
    text = _RE_BEARER.sub("[REDACTED_SECRET]", text)
    text = _RE_BASE64.sub("[REDACTED_BASE64]", text)
    text = _RE_URL.sub("[REDACTED_LONG_URL]", text)
    return text


def _segment_min_chars(priority: int) -> int:
    if priority <= 1:
        return 10**9
    if priority == 2:
        return 120
    if priority == 3:
        return 80
    if priority == 4:
        return 60
    return 40


def _set_field(parts: ReactContextParts, name: str, value: str) -> None:
    setattr(parts, name, value)


def _get_field(parts: ReactContextParts, name: str) -> str:
    return str(getattr(parts, name, "") or "")


_DYNAMIC_FIELDS: tuple[tuple[str, int], ...] = (
    ("task", 1),
    ("system_model", 2),
    ("dst_summary", 3),
    ("skills_desc", 4),
    ("trajectory", 5),
)


def _summarize_text(
    chat_model: BaseChatModel,
    text: str,
    style: str,
    max_out_tokens: int,
) -> str:
    prompt = (
        "请将下列上下文压缩为更短的要点列表，保留关键事实与专有名词，不要编造。"
        f"风格：{style}\n\n---\n{text}\n---"
    )
    try:
        resp = chat_model.invoke([HumanMessage(content=prompt)])
        raw = getattr(resp, "content", None) or str(resp)
        out = str(raw).strip()
        if not out:
            return text
        cap = max_out_tokens * 4
        if len(out) > cap:
            out = out[:cap] + "…"
        return out
    except Exception:
        _LOG.exception("[context_compression] LLM summarize failed, keeping original slice")
        return text


def run_compression_pipeline(
    parts: ReactContextParts,
    cfg: ContextCompressionConfig,
    chat_model: Optional[BaseChatModel],
    *,
    project_id: Optional[str],
    session_id: str,
    llm_round: int,
    step_id: int,
    knowledge_ingest: Optional[Callable[[str, list[dict[str, Any]]], None]] = None,
) -> str:
    """
    若估算超过 ``context_token_budget * pre_send_threshold`` 则执行流水线，否则原样渲染。
    ``knowledge_ingest`` 签名为 ``(project_id, fragments)``，由调用方注入 ``ProjectKnowledgeService.ingest_truncation_fragments``。
    """
    if not cfg.enabled:
        return render_parts(parts)

    hard_budget = int(cfg.context_token_budget)
    trigger = int(hard_budget * float(cfg.pre_send_threshold))
    cur = total_estimate_tokens(parts)
    if cur <= trigger:
        return render_parts(parts)

    p = parts.clone()
    # 删除：空动态字段
    for fname, _pri in _DYNAMIC_FIELDS:
        v = _get_field(p, fname).strip()
        if fname != "task":
            _set_field(p, fname, v)

    # 遮盖：仅轨迹与 DST（其它块可能含用户意图，少动）
    p.trajectory = redact_sensitive(p.trajectory, cfg)
    p.dst_summary = redact_sensitive(p.dst_summary, cfg)

    # 规范化空白
    for fname, _pri in _DYNAMIC_FIELDS:
        _set_field(p, fname, _collapse_blank_lines(_get_field(p, fname)))

    # 分级摘要（priority 越高数字越大 = 越不重要）
    if cfg.enable_llm_summarization and chat_model is not None:
        min_pri = int(cfg.summarization_min_priority)
        styles = {
            2: "中等压缩，条列项目模型要点",
            3: "中等偏保守，保留 DST 状态要点",
            4: "较强压缩，仅保留技能 id 与一行用途",
            5: "强压缩，每步一行：行动+观察摘要",
        }
        for fname, pri in _DYNAMIC_FIELDS:
            if pri < min_pri:
                continue
            text = _get_field(p, fname)
            if not text:
                continue
            soft = _soft_cap_for_field(p, fname, pri, hard_budget)
            if estimate_tokens(text) <= soft:
                continue
            style = styles.get(pri, "压缩为短要点")
            new_t = _summarize_text(
                chat_model,
                text,
                style,
                int(cfg.summarize_max_tokens_per_call),
            )
            _set_field(p, fname, new_t)

    # 硬截断（从低优先级块开始）
    fragments: list[dict[str, Any]] = []
    marker = (cfg.truncation_marker or "[[UAP_TRUNCATED]]").strip() or "[[UAP_TRUNCATED]]"

    def _apply_truncation() -> None:
        order = sorted(_DYNAMIC_FIELDS, key=lambda x: -x[1])
        safety = 0
        while total_estimate_tokens(p) > hard_budget and safety < 500:
            safety += 1
            tok = total_estimate_tokens(p)
            over = tok - hard_budget
            need_drop = min(max(over * 4, 256), 4000)
            progressed = False
            for fname, pri in order:
                text = _get_field(p, fname)
                if pri <= 1:
                    continue
                min_keep = _segment_min_chars(pri)
                if len(text) <= min_keep + len(marker) + 8:
                    continue
                new_len = max(min_keep, len(text) - int(need_drop))
                if new_len >= len(text):
                    continue
                head = text[:new_len]
                tail = text[new_len:]
                _set_field(p, fname, head + marker)
                if tail.strip():
                    fragments.append(
                        {
                            "text": tail,
                            "segment": fname,
                            "priority": pri,
                            "session_id": session_id,
                            "llm_round": llm_round,
                            "step_id": step_id,
                        }
                    )
                progressed = True
                break
            if not progressed:
                break

    _apply_truncation()

    if (
        cfg.enable_async_truncation_kb
        and knowledge_ingest is not None
        and project_id
        and fragments
    ):

        def _bg() -> None:
            try:
                knowledge_ingest(project_id, fragments)
            except Exception:
                _LOG.exception("[context_compression] async truncation KB ingest failed")

        threading.Thread(target=_bg, name="uap_trunc_kb", daemon=True).start()

    return render_parts(p)


def _soft_cap_for_field(parts: ReactContextParts, fname: str, pri: int, hard_budget: int) -> int:
    """各动态字段在摘要前的软 token 上限（粗分配）。"""
    static_tok = estimate_tokens(
        parts.literal_pre
        + parts.literal_after_task
        + parts.literal_after_system_model
        + parts.literal_after_dst
        + parts.literal_after_skills
        + parts.literal_post
    )
    task_tok = estimate_tokens(parts.task)
    pool = max(256, hard_budget - static_tok - task_tok - int(hard_budget * 0.08))
    weights = {2: 4.0, 3: 3.0, 4: 2.0, 5: 1.0}
    wsum = sum(weights.get(p, 1.0) for _, p in _DYNAMIC_FIELDS if p >= 2)
    base = pool * weights.get(pri, 1.0) / max(wsum, 1.0)
    return max(64, int(base))


def empty_react_context_parts() -> ReactContextParts:
    lit = react_decision_template_literal_parts()
    return ReactContextParts(
        literal_pre=lit[0],
        literal_after_task=lit[1],
        literal_after_system_model=lit[2],
        literal_after_dst=lit[3],
        literal_after_skills=lit[4],
        literal_post=lit[5],
    )
