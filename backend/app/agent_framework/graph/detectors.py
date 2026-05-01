"""Loop detector, drift detector, and citation analyzer.

These are pure functions that consume :class:`AgentState` (and message
lists) and return small dataclasses. They never mutate state; the
critic node is responsible for persisting their output via
``critic_directives`` and ``loop_signals`` / ``drift_signals`` /
``citation_signals``.

Loop detector
-------------
A *loop* is repeated tool invocation with identical name + arguments
across the last :data:`LOOP_WINDOW` tool calls. We canonicalise args via
``json.dumps(sort_keys=True)`` so reorderings don't fool us. Two
identical calls in a row trip the detector immediately; three within
the window trip it regardless of intervening different calls.

Drift detector
--------------
*Drift* is detected when the **last
:data:`DRIFT_TOOL_ERROR_STREAK`** tool calls in a row failed (status
``"error"``). This catches the common pathology where the model keeps
retrying with the same broken arguments. The threshold defaults to 3.

Citation analyzer
-----------------
For runs where ``web_search`` produced results in the last few tool
messages, the assistant's most recent textual answer must include at
least one URL or markdown link (``[text](url)``); otherwise the
analyzer flags ``required=True, satisfied=False``. The critic uses this
signal to inject a citation directive on the next turn.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

LOOP_WINDOW = 4
DRIFT_TOOL_ERROR_STREAK = 3
URL_PATTERN = re.compile(r"https?://[^\s\)\]]+", re.IGNORECASE)
MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]]+\]\(https?://[^\s\)]+\)", re.IGNORECASE)


# ------------------------------------------------------------ loop detector


@dataclass(frozen=True)
class LoopSignal:
    detected: bool = False
    reason: str = ""
    repeated_call: dict[str, Any] | None = None
    count: int = 0
    window: int = LOOP_WINDOW

    def as_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "reason": self.reason,
            "repeated_call": self.repeated_call,
            "count": self.count,
            "window": self.window,
        }


def _canonicalize_call(call: dict[str, Any]) -> str:
    name = str(call.get("name") or "")
    args = call.get("args") or {}
    try:
        args_repr = json.dumps(args, sort_keys=True, default=str)
    except (TypeError, ValueError):
        args_repr = repr(args)
    return f"{name}|{args_repr}"


def detect_loop(messages: list[Any], *, window: int = LOOP_WINDOW) -> LoopSignal:
    """Look for repeated tool invocations in the last ``window`` AI msgs."""

    seen: list[tuple[str, dict[str, Any]]] = []
    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls or []:
            if not isinstance(call, dict):
                continue
            key = _canonicalize_call(call)
            seen.append((key, call))
            if len(seen) >= window:
                break
        if len(seen) >= window:
            break

    if len(seen) < 2:
        return LoopSignal(window=window)

    counts: dict[str, int] = {}
    for key, _call in seen:
        counts[key] = counts.get(key, 0) + 1
    most_common_key, count = max(counts.items(), key=lambda kv: kv[1])
    if count >= 2:
        repeated = next(call for key, call in seen if key == most_common_key)
        # Only call it a loop when the same call appears at least twice.
        return LoopSignal(
            detected=count >= 2,
            reason=f"repeated_tool_call:{count}x",
            repeated_call={
                "name": repeated.get("name"),
                "args": repeated.get("args") or {},
            },
            count=count,
            window=window,
        )
    return LoopSignal(window=window)


# ------------------------------------------------------------- drift detector


@dataclass(frozen=True)
class DriftSignal:
    detected: bool = False
    reason: str = ""
    tool_error_streak: int = 0
    threshold: int = DRIFT_TOOL_ERROR_STREAK

    def as_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "reason": self.reason,
            "tool_error_streak": self.tool_error_streak,
            "threshold": self.threshold,
        }


def detect_drift(
    intermediate_steps: list[dict[str, Any]],
    *,
    threshold: int = DRIFT_TOOL_ERROR_STREAK,
) -> DriftSignal:
    """Count consecutive ``status='error'`` tool steps from the tail."""

    streak = 0
    for step in reversed(intermediate_steps):
        if step.get("node") != "action":
            # Stop counting at the first non-tool record so we only consider
            # the most recent tool batch.
            break
        if step.get("status") == "error":
            streak += 1
            continue
        if step.get("status") in {"ok", "pending_approval"}:
            break
    detected = streak >= threshold
    reason = f"tool_error_streak:{streak}" if detected else ""
    return DriftSignal(
        detected=detected,
        reason=reason,
        tool_error_streak=streak,
        threshold=threshold,
    )


# ------------------------------------------------------------- citations


@dataclass(frozen=True)
class CitationSignal:
    required: bool = False
    satisfied: bool = True
    missing_for_tools: list[str] = field(default_factory=list)
    last_assistant_chars: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "satisfied": self.satisfied,
            "missing_for_tools": list(self.missing_for_tools),
            "last_assistant_chars": self.last_assistant_chars,
        }


_CITATION_REQUIRED_TOOLS = ("web_search",)


def analyze_citations(
    messages: list[Any],
    *,
    citation_required_tools: tuple[str, ...] = _CITATION_REQUIRED_TOOLS,
) -> CitationSignal:
    """Decide whether the latest assistant turn needs a citation note.

    "Needs citation" iff:

    1. The most recent assistant message has *no* tool calls (i.e. it's
       a final response to the user), AND
    2. At least one of the most recent tool messages came from a tool
       in ``citation_required_tools`` (default: ``web_search``).

    The signal flips ``satisfied=False`` only when the assistant text
    contains neither a bare URL nor a markdown link.
    """

    last_assistant: AIMessage | None = None
    tool_messages_since_assistant: list[ToolMessage] = []
    seen_assistant = False
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not seen_assistant:
            last_assistant = message
            seen_assistant = True
            continue
        if seen_assistant:
            if isinstance(message, ToolMessage):
                tool_messages_since_assistant.append(message)
            elif isinstance(message, AIMessage):
                # Earlier assistant turn — stop collecting tool messages.
                break

    if last_assistant is None:
        return CitationSignal()

    # Citation is only meaningful for a *final* assistant turn (no tool
    # calls). If the assistant is asking to call more tools, defer.
    if last_assistant.tool_calls:
        return CitationSignal()

    triggering_tools = [
        tm.name for tm in tool_messages_since_assistant if tm.name in citation_required_tools
    ]
    if not triggering_tools:
        return CitationSignal()

    text = str(last_assistant.content or "")
    has_url = bool(URL_PATTERN.search(text)) or bool(MARKDOWN_LINK_PATTERN.search(text))
    return CitationSignal(
        required=True,
        satisfied=has_url,
        missing_for_tools=[] if has_url else sorted(set(triggering_tools)),
        last_assistant_chars=len(text),
    )
