"""建模 LLM token 流缓冲：后台线程写入，前端通过 poll API 拉取。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class _StreamSession:
    tokens: list[str] = field(default_factory=list)
    done: bool = False
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class ModelingStreamHub:
    """线程安全的 stream_id → token 队列 + 最终结果。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, _StreamSession] = {}

    def create(self, stream_id: str) -> None:
        with self._lock:
            self._sessions[stream_id] = _StreamSession()

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
