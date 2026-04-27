"""Loop eval — detector fires on repeated tool calls."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from ...graph.detectors import detect_loop
from .report import EvalReport


def eval_loop(_store: Any | None = None) -> EvalReport:
    report = EvalReport(suite="loop")

    def _msg(call: dict[str, Any]) -> AIMessage:
        return AIMessage(content="", tool_calls=[call])

    repeat_call = {"id": "1", "name": "web_search", "args": {"query": "tommy"}}
    different_call = {"id": "2", "name": "web_search", "args": {"query": "different"}}

    repeated_history = [_msg(repeat_call), _msg(repeat_call)]
    signal = detect_loop(repeated_history)
    report.add(
        "loop_detected_when_call_repeats",
        passed=signal.detected and signal.count >= 2,
        detail=f"detected={signal.detected}, count={signal.count}",
    )

    diverse_history = [_msg(repeat_call), _msg(different_call)]
    signal = detect_loop(diverse_history)
    report.add(
        "loop_not_detected_when_calls_differ",
        passed=not signal.detected,
        detail=f"detected={signal.detected}",
    )
    return report
