"""
UAP 卡片管理器

管理卡片的生命周期：创建、等待响应、处理响应
"""

import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Callable, Optional

from uap.card.models import (
    CardType,
    CardContext,
    CardResponse,
    ConfirmationCard
)


class CardManager:
    """卡片管理器"""
    
    def __init__(self, default_timeout: int = 300):
        """
        初始化卡片管理器
        
        Args:
            default_timeout: 默认卡片超时时间（秒）
        """
        self._default_timeout = default_timeout
        self._pending_cards: dict[str, ConfirmationCard] = {}  # card_id -> card
        self._card_history: list[ConfirmationCard] = []  # 历史卡片
        self._responses: dict[str, CardResponse] = {}  # card_id -> response
        self._waiting_threads: dict[str, threading.Event] = {}  # card_id -> event
        self._callbacks: dict[CardType, list[Callable]] = defaultdict(list)  # type -> callbacks
        self._lock = threading.Lock()
    
    def register_callback(self, card_type: CardType, callback: Callable[[CardResponse], None]):
        """注册卡片响应回调"""
        with self._lock:
            self._callbacks[card_type].append(callback)
    
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
            
            return card.card_id
    
    def get_pending_cards(self) -> list[ConfirmationCard]:
        """获取所有待处理的卡片"""
        with self._lock:
            self._cleanup_expired()
            return list(self._pending_cards.values())
    
    def get_card(self, card_id: str) -> Optional[ConfirmationCard]:
        """获取指定卡片"""
        with self._lock:
            return self._pending_cards.get(card_id)
    
    def get_pending_card_for_project(self, project_id: str) -> Optional[ConfirmationCard]:
        """获取指定项目的待处理卡片"""
        with self._lock:
            self._cleanup_expired()
            for card in self._pending_cards.values():
                if card.context.get("project_id") == project_id:
                    return card
            return None
    
    def has_pending_card(self, project_id: Optional[str] = None) -> bool:
        """检查是否有待处理的卡片"""
        with self._lock:
            self._cleanup_expired()
            if project_id is None:
                return len(self._pending_cards) > 0
            return self.get_pending_card_for_project(project_id) is not None
    
    def _cleanup_expired(self):
        """清理过期的卡片"""
        now = datetime.now()
        expired_ids = [
            card_id for card_id, card in self._pending_cards.items()
            if card.expires_at and card.expires_at < now
        ]
        for card_id in expired_ids:
            del self._pending_cards[card_id]
            if card_id in self._waiting_threads:
                self._waiting_threads[card_id].set()  # 释放等待线程
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
        with self._lock:
            card = self._pending_cards.get(response.card_id)
            if card is None:
                return False
            
            # 保存响应
            self._responses[response.card_id] = response
            
            # 从待处理移除
            del self._pending_cards[response.card_id]
            
            # 添加到历史
            self._card_history.append(card)
            
            # 释放等待线程
            if response.card_id in self._waiting_threads:
                self._waiting_threads[response.card_id].set()
                del self._waiting_threads[response.card_id]
            
            # 触发回调
            self._trigger_callbacks(card.card_type, response)
            
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
