"""CardPersistence SQLite 与 CardManager 挂钩。"""

from __future__ import annotations

import uuid

import pytest

from uap.card.manager import CardManager
from uap.card.models import CardOption, CardPriority, CardResponse, CardType, ConfirmationCard
from uap.card.persistence import CardPersistence


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "cards.sqlite"


def test_persistence_insert_and_respond(db_path):
    p = CardPersistence(db_path)
    assert p.enabled
    cid = str(uuid.uuid4())
    card = ConfirmationCard(
        card_id=cid,
        card_type=CardType.MODEL_CONFIRM,
        title="t",
        content="body",
        options=[CardOption(id="confirm", label="OK")],
        priority=CardPriority.NORMAL,
        context={"project_id": "proj1"},
    )
    p.insert_pending(card)
    rows = p.list_by_project("proj1", limit=10)
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert rows[0]["card_id"] == cid

    from datetime import datetime

    p.update_responded(cid, "confirm", {"project_id": "proj1"}, datetime.now())
    rows2 = p.list_by_project("proj1", limit=10)
    assert rows2[0]["status"] == "responded"
    assert rows2[0]["selected_option_id"] == "confirm"


def test_persistence_expired(db_path):
    p = CardPersistence(db_path)
    cid = str(uuid.uuid4())
    card = ConfirmationCard(
        card_id=cid,
        card_type=CardType.SKILL_DRAFT_CONFIRM,
        title="s",
        content="c",
        options=[],
        context={"project_id": "p2"},
    )
    p.insert_pending(card)
    p.update_status_expired(cid)
    rows = p.list_by_project("p2", limit=5)
    assert rows[0]["status"] == "expired"


def test_card_manager_persists_lifecycle(db_path):
    p = CardPersistence(db_path)
    cm = CardManager(default_timeout=300, persistence=p)
    cid = str(uuid.uuid4())
    card = ConfirmationCard(
        card_id=cid,
        card_type=CardType.ASK_USER,
        title="ask",
        content="?",
        options=[CardOption(id="a", label="A")],
        context={"project_id": "px"},
    )
    cm.create_card(card)
    rows = p.list_by_project("px", 5)
    assert len(rows) == 1 and rows[0]["status"] == "pending"

    assert cm.submit_response(CardResponse(card_id=cid, selected_option_id="a"))
    rows2 = p.list_by_project("px", 5)
    assert rows2[0]["status"] == "responded"
