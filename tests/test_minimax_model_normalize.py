"""MiniMax model 参数规范化（避免 unknown model）。"""

from uap.infrastructure.llm.langchain_chat_model import _normalize_minimax_model_id


def test_minimax_alias_minimax_space_27() -> None:
    assert _normalize_minimax_model_id("minimax 2.7") == "MiniMax-M2.7"


def test_minimax_preserves_official_id() -> None:
    assert _normalize_minimax_model_id("MiniMax-M2.7") == "MiniMax-M2.7"


def test_minimax_highspeed_alias() -> None:
    assert _normalize_minimax_model_id("minimax 2.7 highspeed") == "MiniMax-M2.7-highspeed"
