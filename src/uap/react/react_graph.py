"""兼容入口：实现位于 ``uap.core.action.react.react_graph``。"""

from uap.core.action.react.react_graph import (
    _llm_chunks_to_message,
    _repeated_failure_circuit_tripped,
    _tool_call_to_name_args,
    compile_react_graph,
)

__all__ = [
    "_llm_chunks_to_message",
    "_repeated_failure_circuit_tripped",
    "_tool_call_to_name_args",
    "compile_react_graph",
]
