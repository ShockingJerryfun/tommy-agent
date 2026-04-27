from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage, SystemMessage

from .context_builder import ContextBuilder, ContextBuildRequest, RenderedContext
from .state import AgentState
from .storage import get_agent_store

_store = get_agent_store()
_builder = ContextBuilder(store=_store)


def render_context(state: AgentState) -> RenderedContext:
    return _builder.build(ContextBuildRequest(state=state))


def render_system_prompt(state: AgentState) -> str:
    return render_context(state).content


def messages_with_context(
    state: AgentState,
    *,
    persist_snapshot: bool = True,
) -> tuple[list[BaseMessage], RenderedContext]:
    rendered = render_context(state)
    if persist_snapshot:
        _persist_snapshot(state, rendered)
    return [SystemMessage(content=rendered.content), *state.get("messages", [])], rendered


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
