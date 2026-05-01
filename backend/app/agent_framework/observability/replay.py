"""Replay harness — re-execute a session through a deterministic runner.

The harness loads a session's persisted user messages and feeds them
into a runner callable. The runner returns a final response and a
list of intermediate steps. The harness does *not* assume real LLM
calls; tests inject a deterministic runner. In production, the
default runner builds the real LangGraph and invokes it under a
checkpointer.

The output is a :class:`ReplayReport` with per-input outcomes plus
aggregate signals (citation count, turn count) that the eval suites
consume.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..storage import PostgresAgentStore

_CITATION_RX = re.compile(r"https?://\S+|\[[^\]]+\]\([^)]+\)")


@dataclass
class ReplayOutcome:
    user_input: str
    final_response: str
    citation_count: int
    tool_count: int
    error: str | None = None


@dataclass
class ReplayReport:
    session_id: str
    outcomes: list[ReplayOutcome] = field(default_factory=list)
    total_inputs: int = 0
    total_citations: int = 0
    total_tools: int = 0
    errors: int = 0

    def succeeded(self) -> bool:
        return self.errors == 0 and self.total_inputs > 0


@dataclass
class RunEventsReplayReport:
    run_id: str
    events: list[dict[str, Any]]
    event_count: int
    event_types: list[str]
    reconstructed_text: str
    terminal_event: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "events": self.events,
            "event_count": self.event_count,
            "event_types": self.event_types,
            "reconstructed_text": self.reconstructed_text,
            "terminal_event": self.terminal_event,
        }


ReplayRunner = Callable[[str, dict[str, Any]], dict[str, Any]]
"""Callable that executes a single user message and returns a result.

Inputs:

- ``user_input`` — the user message string.
- ``context`` — per-replay context (``session_id``, ``agent_id``, etc.).

Returns a dict with ``final_response: str`` and optionally
``intermediate_steps`` (a list of dicts) used to count tools.
"""


def default_replay_runner(
    user_input: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Production runner: real LangGraph + Postgres checkpointer."""

    from langchain_core.messages import AIMessage, HumanMessage

    from ..agent import build_agent_graph
    from ..runtime.checkpointing import build_thread_config, create_checkpointer

    graph = build_agent_graph(checkpointer=create_checkpointer())
    thread_id = str(context.get("thread_id") or context.get("session_id") or "replay")
    state = graph.invoke(
        {
            "session_id": thread_id,
            "agent_id": str(context.get("agent_id") or "default"),
            "metadata": {"replay": True},
            "messages": [HumanMessage(content=user_input)],
        },
        config=build_thread_config(thread_id),
    )
    final = ""
    for message in reversed(state.get("messages", [])):
        if isinstance(message, AIMessage) and message.content:
            final = str(message.content)
            break
    return {
        "final_response": final,
        "intermediate_steps": state.get("intermediate_steps", []),
    }


def replay_session(
    store: PostgresAgentStore,
    *,
    session_id: str,
    runner: ReplayRunner | None = None,
    max_inputs: int = 10,
) -> ReplayReport:
    """Replay a session's user messages through ``runner``."""

    runner = runner or default_replay_runner
    history = store.list_messages(session_id, limit=max_inputs * 4)
    user_inputs: list[str] = []
    for message in history:
        role = getattr(message, "role", None) or (
            message.get("role") if isinstance(message, dict) else None
        )
        if role != "user":
            continue
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")
        user_inputs.append(str(content or ""))
        if len(user_inputs) >= max_inputs:
            break

    report = ReplayReport(session_id=session_id, total_inputs=len(user_inputs))
    for user_input in user_inputs:
        try:
            result = runner(user_input, {"session_id": session_id})
        except Exception as exc:  # noqa: BLE001 — replay must not raise.
            report.outcomes.append(
                ReplayOutcome(
                    user_input=user_input,
                    final_response="",
                    citation_count=0,
                    tool_count=0,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            report.errors += 1
            continue
        final = str(result.get("final_response") or "")
        steps = result.get("intermediate_steps") or []
        tool_count = sum(1 for step in steps if step.get("tool"))
        citations = len(_CITATION_RX.findall(final))
        report.outcomes.append(
            ReplayOutcome(
                user_input=user_input,
                final_response=final,
                citation_count=citations,
                tool_count=tool_count,
            )
        )
        report.total_citations += citations
        report.total_tools += tool_count

    return report


def replay_run_events(
    store: PostgresAgentStore,
    *,
    run_id: str,
    runner: Callable[..., Any] | None = None,
    limit: int = 1000,
) -> RunEventsReplayReport:
    """Replay a run from persisted run_events only.

    ``runner`` is accepted only as a guard seam for tests and is never invoked:
    this replay path intentionally does not call models or tools.
    """

    del runner
    rows = store.list_run_events_after(run_id, after_sequence=None, limit=limit)
    events = [dict(row) for row in rows]
    text_parts: list[str] = []
    terminal_event: str | None = None
    for row in events:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        event_type = str(row.get("type") or "")
        agent_event = payload.get("agent_event") if isinstance(payload, dict) else None
        if isinstance(agent_event, dict) and isinstance(agent_event.get("type"), str):
            event_type = agent_event["type"]
            data = agent_event.get("data") if isinstance(agent_event.get("data"), dict) else {}
        else:
            data = payload
        if event_type == "message_delta":
            text_parts.append(str(data.get("content") or ""))
        if event_type in {"done", "error", "cancelled", "interrupted", "stopped"}:
            terminal_event = event_type
    return RunEventsReplayReport(
        run_id=run_id,
        events=events,
        event_count=len(events),
        event_types=[str(event.get("type") or "") for event in events],
        reconstructed_text="".join(text_parts),
        terminal_event=terminal_event,
    )
