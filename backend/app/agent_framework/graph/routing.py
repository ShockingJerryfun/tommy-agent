from __future__ import annotations

from typing import Any, Literal

from langchain_core.messages import AIMessage, ToolMessage

from ..state import AgentState
from ..storage import get_agent_store
from .exceptions import RunStopped

Route = Literal["action", "end"]
ActionRoute = Literal["agent", "end"]
AgentRoute = Literal["action", "critic"]
CriticRoute = Literal["agent", "reflector"]


def tool_calls(message: Any) -> list[dict[str, Any]]:
    if isinstance(message, AIMessage):
        return list(message.tool_calls or [])
    return list(getattr(message, "tool_calls", []) or [])


def should_continue(state: AgentState) -> Route:
    if run_stop_requested(state):
        return "end"
    messages = state.get("messages", [])
    if not messages:
        return "end"
    return "action" if tool_calls(messages[-1]) else "end"


def should_continue_after_action(state: AgentState) -> ActionRoute:
    return "end" if run_stop_requested(state) else "agent"


def approval_is_pending(state: AgentState) -> bool:
    steps = state.get("intermediate_steps") or []
    return any(
        isinstance(step, dict) and step.get("status") == "pending_approval"
        for step in steps
    )


def route_after_agent(state: AgentState) -> AgentRoute:
    """v2 routing: tool calls go to action; everything else to the critic.

    The critic is now the gatekeeper between agent turns; routing
    "no tool calls" to the critic gives it a chance to detect citation
    misses and run the terminal budget tally before we close the run.
    """

    if run_stop_requested(state):
        return "critic"
    messages = state.get("messages", []) or []
    if not messages:
        return "critic"
    return "action" if tool_calls(messages[-1]) else "critic"


def route_after_critic(state: AgentState) -> CriticRoute:
    """Decide whether to loop back to ``agent`` or terminate via ``reflector``.

    Hard stops (route to ``reflector``):

    - User stop requested.
    - Budget exhausted.
    - Loop or drift detected.

    Otherwise:

    - If the last message is a ``ToolMessage`` (i.e. ``action`` just
      ran), loop back to ``agent`` so the model can read the tool
      output and either call more tools or produce its final answer.
    - If the last message is an ``AIMessage`` without tool calls, the
      agent is done — terminate via the reflector.
    - Defensive fallback: an ``AIMessage`` *with* tool calls also
      loops back so the next turn can dispatch them.
    """

    if run_stop_requested(state):
        return "reflector"
    if approval_is_pending(state):
        return "reflector"
    budget = state.get("budget") or {}
    if budget.get("exhausted"):
        return "reflector"
    if (state.get("loop_signals") or {}).get("detected"):
        return "reflector"
    if (state.get("drift_signals") or {}).get("detected"):
        return "reflector"

    messages = state.get("messages", []) or []
    if not messages:
        return "reflector"
    last = messages[-1]
    if isinstance(last, ToolMessage) or getattr(last, "type", "") == "tool":
        return "agent"
    if tool_calls(last):
        return "agent"
    return "reflector"


def state_run_id(state: AgentState) -> str:
    metadata = state.get("metadata", {})
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get("run_id") or "")


def run_stop_requested(state: AgentState) -> bool:
    metadata = state.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    store = get_agent_store()
    session_id = str(state.get("session_id") or "")
    run_id = state_run_id(state)
    if store.run_stop_requested(session_id=session_id, run_id=run_id):
        return True

    parent_session_id = str(metadata.get("parent_session_id") or "")
    parent_run_id = str(metadata.get("parent_run_id") or "")
    return store.run_stop_requested(session_id=parent_session_id, run_id=parent_run_id)


def raise_if_stopped(state: AgentState) -> None:
    if run_stop_requested(state):
        raise RunStopped("Run was stopped by the user.")
