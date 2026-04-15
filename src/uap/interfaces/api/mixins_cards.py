"""HITL 卡片 API。"""

from __future__ import annotations

from typing import Optional

from uap.card import CardContext, CardResponse


class CardsApiMixin:
    def get_pending_card(self, project_id: str) -> Optional[dict]:
        """Get pending card for project"""
        card = self.card_manager.get_pending_card_for_project(project_id)
        return card.to_dict() if card else None

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

    def get_card_history(self, project_id: str, limit: int = 50) -> list[dict]:
        """Get card history"""
        cards = self.card_manager.get_card_history_for_project(project_id, limit)
        return [card.to_dict() for card in cards]
