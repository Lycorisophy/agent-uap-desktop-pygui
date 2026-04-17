"""将 ReAct ``ask_user`` 一步转为可确认的 ``ConfirmationCard``。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from uap.card.models import CardOption, CardPriority, CardType, ConfirmationCard


def build_ask_user_confirmation_card(
    project_id: str,
    session_id: str,
    step_id: int,
    action_input: dict[str, Any],
    *,
    expires_in_seconds: int,
) -> ConfirmationCard:
    raw_q = action_input.get("question") or action_input.get("raw") or ""
    question = str(raw_q).strip() or "请补充信息"
    options: list[CardOption] = []
    opts_raw = action_input.get("options")
    if isinstance(opts_raw, list):
        for i, o in enumerate(opts_raw):
            if isinstance(o, dict):
                label = str(o.get("label") or o.get("text") or o.get("question") or "").strip()
                oid = str(o.get("id") if o.get("id") is not None else i)
            else:
                label = str(o).strip()
                oid = str(i)
            if not label:
                continue
            options.append(CardOption(id=oid, label=label))
    real_count = len(options)
    options.append(
        CardOption(
            id="__reject__",
            label="跳过 / 暂不回答",
            description="不调用大模型，仅结束本次追问",
        )
    )
    rec = action_input.get("recommended_option_id")
    default_id: str | None
    if rec is not None and str(rec).strip():
        default_id = str(rec).strip()
    elif real_count > 0:
        default_id = options[0].id
    else:
        default_id = "__reject__"
    now = datetime.now()
    ttl = max(1, min(900, int(expires_in_seconds)))
    return ConfirmationCard(
        card_id=str(uuid.uuid4()),
        card_type=CardType.ASK_USER,
        title="需要你的确认",
        content=question,
        options=options,
        priority=CardPriority.NORMAL,
        default_option_id=default_id,
        context={
            "project_id": project_id,
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "modeling",
        },
        created_at=now,
        expires_at=now + timedelta(seconds=ttl),
        requires_confirmation=True,
        icon="❓",
    )
