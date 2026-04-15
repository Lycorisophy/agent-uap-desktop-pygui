"""从各后端 ``chat`` 返回值中取出 assistant 纯文本。"""

from __future__ import annotations

from typing import Any


def assistant_text_from_chat_response(resp: Any) -> str:
    """
    统一解析 ``chat`` 返回值：
    - Ollama 原生：``{"message": {"content": "..."}}``
    - OpenAI 兼容（未包装时）：``{"choices": [{"message": {"content": "..."}}]}``
    - 已是 ``str``：原样返回
    """
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    if not isinstance(resp, dict):
        return str(resp)

    msg = resp.get("message")
    if isinstance(msg, dict) and "content" in msg:
        return str(msg.get("content") or "")

    choices = resp.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            m = first.get("message")
            if isinstance(m, dict) and m.get("content") is not None:
                return str(m.get("content") or "")

    if "content" in resp:
        return str(resp.get("content") or "")

    return ""
