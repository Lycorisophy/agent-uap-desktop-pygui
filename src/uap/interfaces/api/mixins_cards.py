"""HITL 卡片 API。"""

from __future__ import annotations

from typing import Any, Optional

from uap.card import CardContext, CardResponse


class CardsApiMixin:
    def get_pending_card(self, project_id: str) -> Optional[dict]:
        """Get pending card for project"""
        card = self.card_manager.get_pending_card_for_project(project_id)
        return card.to_dict() if card else None

    def get_pending_ask_user_card(self, project_id: str) -> Optional[dict]:
        """返回当前项目待处理的建模追问卡（ASK_USER），无则 None。"""
        card = self.card_manager.get_pending_ask_user_card_for_project(project_id)
        return card.to_dict() if card else None

    def reject_pending_ask_user(self, project_id: str, reason: str = "user_rejected") -> dict:
        """
        显式拒绝待处理追问卡：提交拒绝语义、触发仅写会话回调，不调用建模 LLM。
        """
        if not project_id or project_id == "undefined":
            return {"ok": False, "message": "Invalid project ID"}
        card = self.card_manager.get_pending_ask_user_card_for_project(project_id)
        if card is None:
            return {"ok": False, "message": "no_pending_ask_user_card"}
        response = CardResponse(
            card_id=card.card_id,
            selected_option_id="__reject__",
            metadata={"reason": str(reason or "user_rejected"), "project_id": project_id},
        )
        ok = self.card_manager.submit_response(response)
        return {"ok": ok, "card_id": card.card_id}

    def get_all_pending_cards(self) -> list[dict]:
        """Get all pending cards"""
        cards = self.card_manager.get_pending_cards()
        return [card.to_dict() for card in cards]

    def submit_card_response(self, card_id: str, selected_option_id: str) -> dict:
        """Submit card response"""
        response = CardResponse(
            card_id=card_id,
            selected_option_id=selected_option_id,
        )
        success = self.card_manager.submit_response(response)
        return {"success": success, "card_id": card_id}

    def dismiss_card(self, card_id: str) -> dict:
        """Dismiss card"""
        success = self.card_manager.dismiss_card(card_id, "user_dismissed")
        return {"success": success, "card_id": card_id}

    def create_model_confirm_card(
        self,
        project_id: str,
        variables: list[dict],
        relations: list[dict],
        constraints: list[dict],
    ) -> dict:
        """Create model confirmation card"""
        context = CardContext(project_id=project_id)
        card = self.card_generator.generate_model_confirm_card(
            context, variables, relations, constraints
        )
        self.card_manager.create_card(card)
        return {"success": True, "card": card.to_dict()}

    def create_prediction_method_card(self, project_id: str) -> dict:
        """Create prediction method selection card"""
        context = CardContext(project_id=project_id, task_type="prediction")
        methods = self.card_generator.get_default_prediction_methods()
        card = self.card_generator.generate_prediction_method_card(context, methods)
        self.card_manager.create_card(card)
        return {"success": True, "card": card.to_dict()}

    def create_prediction_execution_card(
        self,
        project_id: str,
        method_name: str,
        horizon: int,
        frequency: int,
    ) -> dict:
        """Create prediction execution confirmation card"""
        context = CardContext(project_id=project_id, task_type="prediction")
        card = self.card_generator.generate_prediction_execution_card(
            context, method_name, horizon, frequency
        )
        self.card_manager.create_card(card)
        return {"success": True, "card": card.to_dict()}

    def get_card_history(self, project_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """
        项目卡片时间线：SQLite 持久化为主，并与内存中仍 pending 的卡片合并（按 card_id 去重）。
        """
        if not project_id or project_id == "undefined":
            return []
        db_rows: list[dict[str, Any]] = []
        cp = getattr(self, "card_persistence", None)
        if cp is not None and getattr(cp, "enabled", False):
            db_rows = cp.list_by_project(project_id, limit=max(1, limit * 2))

        by_id: dict[str, dict[str, Any]] = {str(r["card_id"]): r for r in db_rows}

        for card in self.card_manager.get_pending_cards():
            pid = str((card.context or {}).get("project_id") or "")
            if pid != str(project_id):
                continue
            d = card.to_dict()
            d["status"] = "pending"
            by_id[card.card_id] = d

        merged = list(by_id.values())
        merged.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
        return merged[: max(1, int(limit))]
