"""
建模前意图 / 场景分类：基于最近 N 轮持久化对话，调用可配置（默认同主 LLM）的小模型一次。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage

from uap.config import LLMConfig, UapConfig
from uap.infrastructure.llm.langchain_chat_model import create_langchain_chat_model
from uap.infrastructure.llm.response_text import assistant_text_from_chat_response
from uap.prompts import PromptId, render

_LOG = logging.getLogger("uap.modeling_intent_classifier")

_VALID_INTENTS = frozenset(
    {
        "prediction",
        "anomaly_detection",
        "system_modeling",
        "analysis",
        "general",
    }
)


def _keyword_intent_fallback(query: str) -> str:
    q = (query or "").lower()
    if any(kw in q for kw in ["预测", "forecast", "predict", "未来"]):
        return "prediction"
    if any(kw in q for kw in ["异常", "anomaly", "异常检测"]):
        return "anomaly_detection"
    if any(kw in q for kw in ["建模", "model", "系统"]):
        return "system_modeling"
    if any(kw in q for kw in ["分析", "analyze", "分析"]):
        return "analysis"
    return "general"


def effective_classifier_llm(cfg: UapConfig) -> LLMConfig:
    """分类用 LLM：无独立配置时用主 llm；否则与主 llm 按字段合并。"""
    ov = cfg.agent.modeling_classifier_llm
    if ov is None:
        return cfg.llm
    base = cfg.llm.model_dump()
    patch = ov.model_dump(mode="json", exclude_none=True)
    base.update(patch)
    return LLMConfig.model_validate(base)


def format_messages_for_classifier(messages: list[dict], rounds: int) -> str:
    """
    取「当前用户句」+ 向前最多 ``rounds`` 组 user→assistant，格式化为可读文本。
    ``messages`` 须已含当前用户消息（列表最后一条通常为 user）。
    """
    if rounds <= 0 or not messages:
        return ""
    tail_n = 1 + 2 * int(rounds)
    tail = messages[-tail_n:]
    lines: list[str] = []
    for m in tail:
        if not isinstance(m, dict):
            continue
        role = (m.get("role") or "").strip().lower()
        if role not in ("user", "assistant"):
            continue
        label = "用户" if role == "user" else "助手"
        text = (m.get("content") or "").strip()
        if len(text) > 8000:
            text = text[:7999] + "…"
        lines.append(f"[{label}] {text}")
    return "\n\n".join(lines)


MODELING_PRIOR_DIALOGUE_MAX_CHARS = 12000


def format_prior_messages_dialogue_block(
    prior_messages: list[dict],
    *,
    max_chars: int = MODELING_PRIOR_DIALOGUE_MAX_CHARS,
) -> str:
    """
    将「当前用户句之前」的消息格式化为可读块，供 ReAct/Plan 主任务文本使用。
    超长时保留尾部，避免丢失最近上下文。
    """
    lines: list[str] = []
    for m in prior_messages:
        if not isinstance(m, dict):
            continue
        role = (m.get("role") or "").strip().lower()
        if role not in ("user", "assistant"):
            continue
        label = "用户" if role == "user" else "助手"
        text = (m.get("content") or "").strip()
        if len(text) > 8000:
            text = text[:7999] + "…"
        lines.append(f"[{label}] {text}")
    block = "\n\n".join(lines).strip()
    if not block:
        return ""
    if len(block) <= max_chars:
        return block
    tail = block[-(max_chars - 24) :].lstrip()
    return "…（前段已省略）\n\n" + tail


def build_modeling_task_with_prior_dialogue(
    prior_messages: list[dict],
    latest_user_message: str,
    *,
    max_prior_chars: int = MODELING_PRIOR_DIALOGUE_MAX_CHARS,
) -> str:
    """将历史对话与本轮用户输入合并为传给主建模智能体的任务描述。"""
    last = (latest_user_message or "").strip()
    block = format_prior_messages_dialogue_block(
        prior_messages, max_chars=max_prior_chars
    )
    if not block:
        return last
    return (
        "【此前对话（理解上下文；请在本轮用户输入基础上继续）】\n"
        f"{block}\n\n"
        "---\n\n"
        "【本轮用户输入】\n"
        f"{last}"
    )


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    for i, ch in enumerate(raw):
        if ch != "{":
            continue
        for j in range(len(raw) - 1, i, -1):
            if raw[j] != "}":
                continue
            chunk = raw[i : j + 1]
            try:
                obj = json.loads(chunk)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue
    return None


def classify_intent_scene(cfg: UapConfig, dialogue_text: str, current_user_line: str) -> dict[str, str]:
    """
    调用分类模型，返回 ``classified_intent``、``classified_scene`` 键。
    解析失败时用关键词回退 intent，scene 为 ``general``。
    """
    fb_intent = _keyword_intent_fallback(current_user_line)
    if not (dialogue_text or "").strip():
        return {"classified_intent": fb_intent, "classified_scene": "general"}

    llm_cfg = effective_classifier_llm(cfg)
    try:
        model = create_langchain_chat_model(llm_cfg)
        prompt = render(PromptId.MODELING_INTENT_CLASSIFY_USER, dialogue=dialogue_text)
        resp = model.invoke([HumanMessage(content=prompt)])
        text = assistant_text_from_chat_response(resp)
        obj = _extract_json_object(str(text))
        if not obj:
            _LOG.debug("[IntentClassifier] JSON parse failed, snippet=%r", text[:400])
            return {"classified_intent": fb_intent, "classified_scene": "general"}
        raw_intent = (obj.get("intent") or "").strip().lower()
        intent = raw_intent if raw_intent in _VALID_INTENTS else fb_intent
        scene = (obj.get("scene") or "").strip() or "general"
        if len(scene) > 64:
            scene = scene[:63] + "…"
        return {"classified_intent": intent, "classified_scene": scene}
    except Exception:
        _LOG.exception("[IntentClassifier] invoke failed")
        return {"classified_intent": fb_intent, "classified_scene": "general"}


def run_modeling_intent_scene_if_enabled(
    cfg: UapConfig,
    messages: list[dict],
    current_user_message: str,
) -> dict[str, str]:
    """
    若 ``modeling_intent_context_rounds > 0`` 则跑分类；否则返回空 dict（由 DST 关键词负责 intent）。
    """
    rounds = int(getattr(cfg.agent, "modeling_intent_context_rounds", 0) or 0)
    if rounds <= 0:
        return {}
    dialogue = format_messages_for_classifier(messages, rounds)
    return classify_intent_scene(cfg, dialogue, current_user_message)
