"""统一 DST 卡片管线：完备性谓词、CardManager 移除回调、技能确认处理。"""

from __future__ import annotations

import uuid

import pytest

from uap.application.dst_pipeline import is_modeling_dst_complete, parse_pending_key, pending_skill_draft_key
from uap.card.manager import CardManager
from uap.card.models import CardOption, CardPriority, CardResponse, CardType, ConfirmationCard
from uap.config import UapConfig
from uap.infrastructure.persistence.project_store import ProjectStore
from uap.application.project_service import ProjectService
from uap.project.models import ModelSource, Relation, SystemModel, Variable


def test_is_modeling_dst_complete_requires_both() -> None:
    m = SystemModel(
        name="t",
        source=ModelSource.LLM_EXTRACTED,
        variables=[Variable(name="x")],
        relations=[],
    )
    assert is_modeling_dst_complete(m) is False
    m2 = SystemModel(
        name="t2",
        source=ModelSource.LLM_EXTRACTED,
        variables=[Variable(name="x")],
        relations=[
            Relation(
                name="r1",
                description="d",
                effect_var="y",
            )
        ],
    )
    assert is_modeling_dst_complete(m2) is True


def test_parse_pending_key() -> None:
    assert parse_pending_key("skill_draft:abc") == ("skill_draft", "abc")
    assert parse_pending_key("model_snap:xyz") == ("model_snap", "xyz")


def test_card_manager_notifies_on_submit(tmp_path) -> None:
    cm = CardManager(default_timeout=300)
    seen: list[tuple[str, str]] = []

    def on_rm(card: ConfirmationCard, reason: str) -> None:
        seen.append((card.card_id, reason))

    cm.register_on_pending_card_removed(on_rm)
    cid = str(uuid.uuid4())
    c = ConfirmationCard(
        card_id=cid,
        card_type=CardType.SKILL_DRAFT_CONFIRM,
        title="t",
        content="c",
        options=[CardOption(id="a", label="A")],
        priority=CardPriority.NORMAL,
        context={"project_id": "p1"},
    )
    cm.create_card(c)
    ok = cm.submit_response(CardResponse(card_id=cid, selected_option_id="a"))
    assert ok
    assert seen == [(cid, "responded")]


def test_handle_skill_confirmation_discard(tmp_path) -> None:
    root = tmp_path / "pr"
    root.mkdir()
    store = ProjectStore(str(root), uap_cfg=UapConfig())
    ps = ProjectService(store, UapConfig())
    from uap.core.skills.models import ProjectSkill, SkillCategory

    sk = ProjectSkill(
        skill_id="s1",
        project_id="p1",
        name="n",
        category=SkillCategory.MODELING,
    )
    did = "d1"
    ps._pending_skill_drafts[did] = {"skill": sk}
    r = ps.handle_skill_confirmation(did, False)
    assert r["ok"] is True
    assert did not in ps._pending_skill_drafts
