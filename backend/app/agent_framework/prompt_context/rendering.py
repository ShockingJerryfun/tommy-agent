from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage

from ..state import AgentState
from ..storage import get_agent_store
from .builder import ContextBuilder, ContextBuildRequest, RenderedContext

_store = get_agent_store()
_builder = ContextBuilder(store=_store)


def render_context(state: AgentState) -> RenderedContext:
    return _builder.build(ContextBuildRequest(state=state))


def render_system_prompt(state: AgentState) -> str:
    return render_context(state).content


def sanitize_tool_call_pairs(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Ensure every AIMessage with tool_calls is followed by matching ToolMessages.

    If tool responses are missing (e.g. run was interrupted between the agent
    and action nodes), strip the ``tool_calls`` from the AIMessage so the LLM
    provider does not reject the request.
    """
    if not messages:
        return messages
    result: list[BaseMessage] = []
    for i, msg in enumerate(messages):
        if not isinstance(msg, AIMessage) or not msg.tool_calls:
            result.append(msg)
            continue
        expected_ids = {tc["id"] for tc in msg.tool_calls if tc.get("id")}
        found_ids: set[str] = set()
        for j in range(i + 1, len(messages)):
            subsequent = messages[j]
            if isinstance(subsequent, ToolMessage) and subsequent.tool_call_id in expected_ids:
                found_ids.add(subsequent.tool_call_id)
            elif isinstance(subsequent, AIMessage):
                break
        if found_ids >= expected_ids:
            result.append(msg)
        else:
            patched = AIMessage(
                content=msg.content or "(tool calls were interrupted)",
                id=msg.id,
            )
            result.append(patched)
            # Drop orphaned ToolMessages that reference tool_calls we just stripped
            orphaned = expected_ids - found_ids
            for j in range(i + 1, len(messages)):
                subsequent = messages[j]
                if isinstance(subsequent, ToolMessage) and subsequent.tool_call_id in orphaned:
                    continue  # will be skipped when we reach it in the outer loop
                if isinstance(subsequent, AIMessage):
                    break
    # Second pass: drop ToolMessages whose tool_call_id no longer exists
    valid_call_ids: set[str] = set()
    for msg in result:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            valid_call_ids.update(tc["id"] for tc in msg.tool_calls if tc.get("id"))
    return [
        msg
        for msg in result
        if not isinstance(msg, ToolMessage) or msg.tool_call_id in valid_call_ids
    ]


def messages_with_context(
    state: AgentState,
    *,
    persist_snapshot: bool = True,
) -> tuple[list[BaseMessage], RenderedContext]:
    rendered = render_context(state)
    if persist_snapshot:
        _persist_snapshot(state, rendered)
    raw_messages = list(state.get("messages", []))
    sanitized = sanitize_tool_call_pairs(raw_messages)
    return [SystemMessage(content=rendered.content), *sanitized], rendered


def messages_with_system_prompt(state: AgentState) -> list[BaseMessage]:
    messages, _rendered = messages_with_context(state)
    return messages


def _persist_snapshot(state: AgentState, rendered: RenderedContext) -> None:
    session_id = str(state.get("session_id") or "")
    if not session_id:
        return
    metadata = state.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    run_id_value = metadata.get("run_id")
    run_id = str(run_id_value) if run_id_value else None
    snapshot_meta: dict[str, Any] = {
        "node": "agent",
        "frontend_settings": (
            metadata.get("frontend_settings")
            if isinstance(metadata.get("frontend_settings"), dict)
            else {}
        ),
    }
    _builder.persist_snapshot(
        rendered,
        session_id=session_id,
        agent_id=str(state.get("agent_id") or "default"),
        run_id=run_id,
        model=str(metadata.get("model") or ""),
        metadata=snapshot_meta,
    )
