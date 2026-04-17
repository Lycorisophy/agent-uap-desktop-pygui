"""ask_user 追问卡构建与 CardManager 过期行为。"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from uap.card.manager import CardManager
from uap.card.models import CardResponse, CardType
from uap.react.ask_user_card import build_ask_user_confirmation_card


def test_build_ask_user_card_contains_reject_option() -> None:
    c = build_ask_user_confirmation_card(
        "p1",
        "sid",
        3,
        {"question": "选哪个？", "options": ["A", "B"], "recommended_option_id": "0"},
        expires_in_seconds=60,
    )
    assert c.card_type == CardType.ASK_USER
    ids = [o.id for o in c.options]
    assert "__reject__" in ids
    assert "0" in ids
    assert c.default_option_id == "0"


def test_ask_user_card_expiry_triggers_timeout_response() -> None:
    received: list[str] = []

    def cb(r: CardResponse) -> None:
        received.append(r.selected_option_id)

    m = CardManager(default_timeout=300)
    m.register_callback(CardType.ASK_USER, cb)
    card = build_ask_user_confirmation_card(
        "proj-x",
        "sess",
        1,
        {"question": "Q?", "options": ["x"]},
        expires_in_seconds=1,
    )
    m.create_card(card)
    time.sleep(1.6)
    m.get_pending_cards()
    assert received == ["__timeout__"]


def test_ask_user_reject_triggers_callback() -> None:
    received: list[str] = []

    def cb(r: CardResponse) -> None:
        received.append(r.selected_option_id)

    m = CardManager()
    m.register_callback(CardType.ASK_USER, cb)
    card = build_ask_user_confirmation_card(
        "p1",
        "s",
        1,
        {"question": "?", "options": ["a"]},
        expires_in_seconds=600,
    )
    m.create_card(card)
    ok = m.submit_response(
        CardResponse(
            card_id=card.card_id,
            selected_option_id="__reject__",
            metadata={"reason": "user_rejected", "project_id": "p1"},
        )
    )
    assert ok is True
    assert received == ["__reject__"]
