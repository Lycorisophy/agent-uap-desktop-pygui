"""
建模前意图 / 场景分类：按配置带入最近 N 轮（或仅当前句）持久化对话，调用可配置（默认同主 LLM）的分类模型。
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

_VALID_SCHEDULED_NEXT = frozenset({"prediction", "react", "plan", "none"})


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


def format_single_user_dialogue_line(current_user_message: str) -> str:
    """仅当前用户句，供 ``rounds <= 0`` 时意图分类（仍走分类 LLM，但不带入多轮历史）。"""
    text = (current_user_message or "").strip()
    if len(text) > 8000:
        text = text[:7999] + "…"
    return f"[用户] {text}"


def format_execution_mode_hint(mode_requested: str | None) -> str:
    """注入分类提示词：说明用户在建模入口选择的执行模式。"""
    if not mode_requested or not str(mode_requested).strip():
        return "（系统未传入模式标签；按默认建模流程理解即可。）"
    m = str(mode_requested).strip().lower()
    if m == "react":
        return (
            "用户选择的是 **react**：本轮将按 **ReAct**（逐步 Thought→Action）执行。"
            "请结合下方对话做意图与场景判断。"
        )
    if m == "plan":
        return (
            "用户选择的是 **plan**：本轮将按 **Plan**（先规划再执行）执行。"
            "请结合下方对话做意图与场景判断。"
        )
    if m == "auto":
        return (
            "用户选择的是 **auto**：后续由系统在 **ReAct** 与 **Plan** 中自动择一执行；"
            "分类只需知晓用户未强制指定单一路径，并结合对话判断意图与场景。"
        )
    if m == "ask":
        return (
            "用户选择的是 **ask（只读问答）**：本轮仅允许 **检索/阅读类** 工具（如网络搜索、项目知识库、"
            "只读文件浏览），**不会**执行建模落盘、数据流水线、删改文件等操作。"
            "除下方规定的 JSON 字段外，**必须**输出 `read_only_fit`（布尔）："
            "为 `true` 表示用户诉求**主要**可通过检索与阅读满足；"
            "为 `false` 表示明显需要改模型、写文件、跑数据处理等（助手仍只能以文字说明局限）。"
        )
    if m == "scheduled":
        return (
            "当前为 **scheduled（定时任务辅助模式）**：**非**用户主对话建模入口；由调度器触发，"
            "无用户在旁、**不可用**对话态 DST 聚合与人机确认（HITL）。"
            "请结合下方片段判断意图与场景，并在 JSON 中**必须**输出 `scheduled_next`（见模板），"
            "用于系统选择本轮执行：仅预测、ReAct、Plan，或 `none`。"
        )
    return f"用户请求模式：**{m}**（请结合对话判断意图与场景）。"


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


def _is_scheduled_mode(mode_requested: str | None) -> bool:
    return str(mode_requested or "").strip().lower() == "scheduled"


def _normalize_scheduled_next(raw: Any, fallback: str = "prediction") -> str:
    s = (str(raw) if raw is not None else "").strip().lower()
    return s if s in _VALID_SCHEDULED_NEXT else fallback


def classify_intent_scene(
    cfg: UapConfig,
    dialogue_text: str,
    current_user_line: str,
    *,
    mode_requested: str | None = None,
) -> dict[str, Any]:
    """
    调用分类模型，返回 ``classified_intent``、``classified_scene``，可选 ``classified_read_only_fit``。
    定时任务模式（``mode_requested=scheduled``）时另含 ``classified_scheduled_next``。
    解析失败时用关键词回退 intent，scene 为 ``general``。
    """
    fb_intent = _keyword_intent_fallback(current_user_line)
    scheduled = _is_scheduled_mode(mode_requested)

    def _empty_out() -> dict[str, Any]:
        out: dict[str, Any] = {
            "classified_intent": fb_intent,
            "classified_scene": "general",
            "classified_read_only_fit": None,
        }
        if scheduled:
            out["classified_scheduled_next"] = "prediction"
        return out

    if not (dialogue_text or "").strip():
        return _empty_out()

    llm_cfg = effective_classifier_llm(cfg)
    try:
        model = create_langchain_chat_model(llm_cfg)
        hint = format_execution_mode_hint(mode_requested)
        prompt = render(
            PromptId.MODELING_INTENT_CLASSIFY_USER,
            execution_mode_hint=hint,
            dialogue=dialogue_text,
        )
        resp = model.invoke([HumanMessage(content=prompt)])
        text = assistant_text_from_chat_response(resp)
        obj = _extract_json_object(str(text))
        if not obj:
            _LOG.debug("[IntentClassifier] JSON parse failed, snippet=%r", text[:400])
            return _empty_out()
        raw_intent = (obj.get("intent") or "").strip().lower()
        intent = raw_intent if raw_intent in _VALID_INTENTS else fb_intent
        scene = (obj.get("scene") or "").strip() or "general"
        if len(scene) > 64:
            scene = scene[:63] + "…"
        out: dict[str, Any] = {
            "classified_intent": intent,
            "classified_scene": scene,
            "classified_read_only_fit": None,
        }
        rof = obj.get("read_only_fit")
        if isinstance(rof, bool):
            out["classified_read_only_fit"] = rof
        if scheduled:
            out["classified_scheduled_next"] = _normalize_scheduled_next(
                obj.get("scheduled_next"), fallback="prediction"
            )
        return out
    except Exception:
        _LOG.exception("[IntentClassifier] invoke failed")
        return _empty_out()


def run_modeling_intent_scene_if_enabled(
    cfg: UapConfig,
    messages: list[dict],
    current_user_message: str,
    *,
    mode_requested: str | None = None,
) -> dict[str, Any]:
    """
    每轮建模默认跑意图/场景分类 LLM。

    ``modeling_intent_context_rounds`` 仅控制**带入分类提示的对话轮数**：
    ``0`` 表示只将当前用户句格式化为对话片段（不拼多轮历史），**仍会调用分类**。
    """
    rounds = int(getattr(cfg.agent, "modeling_intent_context_rounds", 0) or 0)
    if rounds <= 0:
        dialogue = format_single_user_dialogue_line(current_user_message)
    else:
        dialogue = format_messages_for_classifier(messages, rounds)
        if not (dialogue or "").strip():
            dialogue = format_single_user_dialogue_line(current_user_message)
    return classify_intent_scene(
        cfg,
        dialogue,
        current_user_message,
        mode_requested=mode_requested,
    )
