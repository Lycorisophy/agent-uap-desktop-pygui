"""建模 LLM token 流缓冲：后台线程写入，前端通过 poll API 拉取。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# 与 ReAct/Plan 图 ``error_message`` 对齐；应用层映射为 ``stop_reason``。
USER_SOFT_STOP = "user_soft_stop"
USER_HARD_STOP = "user_hard_stop"


def get_interrupt_pair_from_context(
    extra_context: dict[str, Any] | None,
) -> tuple[threading.Event, threading.Event] | None:
    """从建模 ``context`` 中解析 ``_interrupt`` 的 soft/hard 事件（与 hub 注入格式一致）。"""
    if not isinstance(extra_context, dict):
        return None
    raw = extra_context.get("_interrupt")
    if not isinstance(raw, dict):
        return None
    soft = raw.get("soft")
    hard = raw.get("hard")
    if not isinstance(soft, threading.Event) or not isinstance(hard, threading.Event):
        return None
    return soft, hard


@dataclass
class _StreamSession:
    tokens: list[str] = field(default_factory=list)
    done: bool = False
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    soft_stop: threading.Event = field(default_factory=threading.Event)
    hard_stop: threading.Event = field(default_factory=threading.Event)


class ModelingStreamHub:
    """线程安全的 stream_id → token 队列 + 最终结果。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, _StreamSession] = {}

    def create(self, stream_id: str) -> None:
        with self._lock:
            self._sessions[stream_id] = _StreamSession()

    def get_interrupt_handles(self, stream_id: str) -> dict[str, threading.Event] | None:
        """返回与 ``context['_interrupt']`` 注入一致的句柄；未知 stream 为 None。"""
        with self._lock:
            s = self._sessions.get(stream_id)
            if not s:
                return None
            return {"soft": s.soft_stop, "hard": s.hard_stop}

    def signal_soft_stop(self, stream_id: str) -> bool:
        with self._lock:
            s = self._sessions.get(stream_id)
            if not s or s.done:
                return False
            s.soft_stop.set()
            return True

    def signal_hard_stop(self, stream_id: str) -> bool:
        with self._lock:
            s = self._sessions.get(stream_id)
            if not s or s.done:
                return False
            s.hard_stop.set()
            return True

    def append_token(self, stream_id: str, text: str) -> None:
        if not text:
            return
        with self._lock:
            s = self._sessions.get(stream_id)
            if not s or s.done:
                return
            s.tokens.append(text)

    def finish(self, stream_id: str, result: dict[str, Any]) -> None:
        with self._lock:
            s = self._sessions.get(stream_id)
            if not s:
                return
            s.done = True
            s.result = result

    def fail(self, stream_id: str, message: str) -> None:
        with self._lock:
            s = self._sessions.get(stream_id)
            if not s:
                return
            s.done = True
            s.error = message or "error"

    def poll(self, stream_id: str) -> dict[str, Any]:
        with self._lock:
            s = self._sessions.get(stream_id)
            if not s:
                return {"ok": False, "error": "unknown_stream_id", "tokens": [], "done": True}
            batch = list(s.tokens)
            s.tokens.clear()
            out: dict[str, Any] = {
                "ok": True,
                "tokens": batch,
                "done": s.done,
            }
            if s.done:
                out["result"] = s.result
                out["error"] = s.error
                del self._sessions[stream_id]
            return out


def run_in_thread(target: Callable[[], None], *, daemon: bool = True) -> None:
    t = threading.Thread(target=target, daemon=daemon)
    t.start()
