"""
UAP 卡片管理器

管理卡片的生命周期：创建、等待响应、处理响应
"""

import logging
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable, Optional

from uap.card.models import (
    CardType,
    CardContext,
    CardResponse,
    ConfirmationCard
)

if TYPE_CHECKING:
    from uap.card.persistence import CardPersistence

_LOG = logging.getLogger("uap.card.manager")


class CardManager:
    """卡片管理器"""
    
    def __init__(self, default_timeout: int = 300, persistence: Optional["CardPersistence"] = None):
        """
        初始化卡片管理器
        
        Args:
            default_timeout: 默认卡片超时时间（秒）
            persistence: 可选 SQLite 持久化（卡片时间线）
        """
        self._default_timeout = default_timeout
        self._persistence = persistence
        self._pending_cards: dict[str, ConfirmationCard] = {}  # card_id -> card
        self._card_history: list[ConfirmationCard] = []  # 历史卡片
        self._responses: dict[str, CardResponse] = {}  # card_id -> response
        self._waiting_threads: dict[str, threading.Event] = {}  # card_id -> event
        self._callbacks: dict[CardType, list[Callable]] = defaultdict(list)  # type -> callbacks
        self._on_pending_removed: list[Callable[[ConfirmationCard, str], None]] = []
        self._lock = threading.Lock()
    
    def register_callback(self, card_type: CardType, callback: Callable[[CardResponse], None]):
        """注册卡片响应回调"""
        with self._lock:
            self._callbacks[card_type].append(callback)

    def register_on_pending_card_removed(
        self, callback: Callable[[ConfirmationCard, str], None]
    ) -> None:
        """
        待处理卡片从 pending 中移除时调用（含用户 submit_response、过期静默删除、关闭等）。
        第二个参数 reason: \"responded\" | \"expired\" | 其它扩展。
        """
        with self._lock:
            self._on_pending_removed.append(callback)
    
    def create_card(self, card: ConfirmationCard) -> str:
        """
        创建并注册一个新卡片
        
        Args:
            card: 确认卡片
            
        Returns:
            card_id: 卡片ID
        """
        with self._lock:
            self._pending_cards[card.card_id] = card
            
            # 设置超时
            if card.expires_at is None:
                card.expires_at = datetime.now() + timedelta(seconds=self._default_timeout)
            
            # 创建等待事件
            self._waiting_threads[card.card_id] = threading.Event()
            
            out_id = card.card_id

        if self._persistence is not None and self._persistence.enabled:
            try:
                self._persistence.insert_pending(card)
            except Exception as e:
                _LOG.error("[CardManager] persistence insert_pending: %s", e)

        return out_id
    
    def get_pending_cards(self) -> list[ConfirmationCard]:
        """获取所有待处理的卡片"""
        self._cleanup_expired()
        with self._lock:
            return list(self._pending_cards.values())
    
    def get_card(self, card_id: str) -> Optional[ConfirmationCard]:
        """获取指定卡片"""
        with self._lock:
            return self._pending_cards.get(card_id)
    
    def get_pending_card_for_project(self, project_id: str) -> Optional[ConfirmationCard]:
        """获取指定项目的待处理卡片"""
        self._cleanup_expired()
        with self._lock:
            for card in self._pending_cards.values():
                if card.context.get("project_id") == project_id:
                    return card
            return None

    def get_pending_ask_user_card_for_project(
        self, project_id: str
    ) -> Optional[ConfirmationCard]:
        """优先返回建模追问卡（ASK_USER），避免与其它 pending 混淆。"""
        self._cleanup_expired()
        with self._lock:
            for card in self._pending_cards.values():
                if (
                    card.card_type == CardType.ASK_USER
                    and str(card.context.get("project_id") or "") == str(project_id)
                ):
                    return card
            return None
    
    def has_pending_card(self, project_id: Optional[str] = None) -> bool:
        """检查是否有待处理的卡片"""
        self._cleanup_expired()
        with self._lock:
            if project_id is None:
                return len(self._pending_cards) > 0
            for card in self._pending_cards.values():
                if card.context.get("project_id") == project_id:
                    return True
            return False
    
    def _cleanup_expired(self) -> None:
        """清理过期卡片；追问卡（ASK_USER）走正式响应以触发回调写会话。"""
        now = datetime.now()
        with self._lock:
            expired_ids = [
                card_id
                for card_id, card in self._pending_cards.items()
                if card.expires_at and card.expires_at < now
            ]
        for card_id in expired_ids:
            with self._lock:
                card = self._pending_cards.get(card_id)
            if card is None:
                continue
            if card.card_type == CardType.ASK_USER:
                pid = (card.context or {}).get("project_id") or ""
                self.submit_response(
                    CardResponse(
                        card_id=card_id,
                        selected_option_id="__timeout__",
                        metadata={"reason": "timeout", "project_id": str(pid)},
                    )
                )
            else:
                if self._persistence is not None and self._persistence.enabled:
                    try:
                        self._persistence.update_status_expired(card_id)
                    except Exception as e:
                        _LOG.error("[CardManager] persistence expired: %s", e)
                with self._lock:
                    card = self._pending_cards.get(card_id)
                if card is not None:
                    self._notify_pending_removed(card, "expired")
                with self._lock:
                    if card_id in self._pending_cards:
                        del self._pending_cards[card_id]
                    if card_id in self._waiting_threads:
                        self._waiting_threads[card_id].set()
                        del self._waiting_threads[card_id]
    
    def wait_for_response(
        self,
        card_id: str,
        timeout: Optional[int] = None
    ) -> Optional[CardResponse]:
        """
        等待卡片响应（阻塞）
        
        Args:
            card_id: 卡片ID
            timeout: 超时时间（秒）
            
        Returns:
            CardResponse 或 None（超时）
        """
        event = self._waiting_threads.get(card_id)
        if event is None:
            return None
        
        # 等待信号
        signaled = event.wait(timeout=timeout or self._default_timeout)
        
        if signaled:
            return self._responses.get(card_id)
        else:
            # 超时
            return None
    
    def submit_response(self, response: CardResponse) -> bool:
        """
        提交卡片响应
        
        Args:
            response: 卡片响应
            
        Returns:
            是否成功
        """
        removed_card: Optional[ConfirmationCard] = None
        with self._lock:
            card = self._pending_cards.get(response.card_id)
            if card is None:
                return False
            
            md = dict(response.metadata or {})
            ctx = getattr(card, "context", None) or {}
            if ctx.get("project_id") and not md.get("project_id"):
                md["project_id"] = str(ctx["project_id"])
            response_for_cb = CardResponse(
                card_id=response.card_id,
                selected_option_id=response.selected_option_id,
                timestamp=response.timestamp,
                metadata=md,
            )
            self._responses[response.card_id] = response_for_cb

            del self._pending_cards[response.card_id]

            self._card_history.append(card)

            if response.card_id in self._waiting_threads:
                self._waiting_threads[response.card_id].set()
                del self._waiting_threads[response.card_id]

            cb_type = card.card_type
            cb_resp = response_for_cb
            removed_card = card

        if self._persistence is not None and self._persistence.enabled and removed_card is not None:
            try:
                self._persistence.update_responded(
                    response.card_id,
                    cb_resp.selected_option_id,
                    cb_resp.metadata,
                    cb_resp.timestamp,
                )
            except Exception as e:
                _LOG.error("[CardManager] persistence update_responded: %s", e)

        if removed_card is not None:
            self._notify_pending_removed(removed_card, "responded")

        self._trigger_callbacks(cb_type, cb_resp)

        return True
    
    def dismiss_card(self, card_id: str, reason: str = "dismissed") -> bool:
        """关闭卡片（用户主动关闭）"""
        response = CardResponse(
            card_id=card_id,
            selected_option_id="dismissed",
            metadata={"reason": reason}
        )
        return self.submit_response(response)
    
    def dismiss_pending_cards(self, project_id: str) -> int:
        """关闭指定项目的所有待处理卡片"""
        count = 0
        with self._lock:
            for card in list(self._pending_cards.values()):
                if card.context.get("project_id") == project_id:
                    card_id = card.card_id
                    self.dismiss_card(card_id, "project_closed")
                    count += 1
        return count
    
    def _notify_pending_removed(self, card: ConfirmationCard, reason: str) -> None:
        listeners = list(self._on_pending_removed)
        for cb in listeners:
            try:
                cb(card, reason)
            except Exception as e:
                print(f"Card on_removed listener error: {e}")

    def _trigger_callbacks(self, card_type: CardType, response: CardResponse):
        """触发注册的回调"""
        callbacks = self._callbacks.get(card_type, [])
        for callback in callbacks:
            try:
                callback(response)
            except Exception as e:
                print(f"Card callback error: {e}")
    
    def get_card_history(self, limit: int = 100) -> list[ConfirmationCard]:
        """获取卡片历史"""
        with self._lock:
            return self._card_history[-limit:]
    
    def get_card_history_for_project(self, project_id: str, limit: int = 50) -> list[ConfirmationCard]:
        """获取指定项目的卡片历史"""
        with self._lock:
            project_cards = [
                card for card in self._card_history
                if card.context.get("project_id") == project_id
            ]
            return project_cards[-limit:]
