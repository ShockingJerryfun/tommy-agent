from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import Runnable
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from .approvals import approval_pending_tool_message, evaluate_tool_call
from .llm import create_llm
from .memory import create_checkpointer
from .prompts import messages_with_system_prompt
from .state import AgentState
from .store import SQLiteAgentStore
from .tools import ToolRegistry, create_default_registry

Route = Literal["action", "end"]
ActionRoute = Literal["agent", "end"]


class RunStopped(RuntimeError):
    """Raised when a run has been explicitly stopped by the user."""


def _tool_calls(message: Any) -> list[dict[str, Any]]:
    if isinstance(message, AIMessage):
        return list(message.tool_calls or [])
    return list(getattr(message, "tool_calls", []) or [])


def should_continue(state: AgentState) -> Route:
    if _run_stop_requested(state):
        return "end"
    messages = state.get("messages", [])
    if not messages:
        return "end"
    return "action" if _tool_calls(messages[-1]) else "end"


def should_continue_after_action(state: AgentState) -> ActionRoute:
    return "end" if _run_stop_requested(state) else "agent"


def _write_stream_event(payload: dict[str, Any]) -> None:
    try:
        writer = get_stream_writer()
    except RuntimeError:
        return
    writer(payload)


def _special_tool_event(name: str, content: str) -> dict[str, Any] | None:
    event_type = {
        "skill_propose": "skill",
        "context_pact_update": "pact",
        "delegate_task": "delegate",
    }.get(name)
    if event_type is None:
        return None
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = {"content": content}
    if isinstance(data, dict):
        return {"type": event_type, **data}
    return {"type": event_type, "content": data}


def _command_scope(metadata: dict[str, Any]) -> str:
    frontend_settings = metadata.get("frontend_settings")
    if isinstance(frontend_settings, dict):
        scope = str(frontend_settings.get("commandScope") or "restricted")
        if scope in {"restricted", "unrestricted"}:
            return scope
    return "restricted"


def _state_run_id(state: AgentState) -> str:
    metadata = state.get("metadata", {})
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get("run_id") or "")


def _run_stop_requested(state: AgentState) -> bool:
    metadata = state.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    store = SQLiteAgentStore()
    session_id = str(state.get("session_id") or "")
    run_id = _state_run_id(state)
    if store.run_stop_requested(session_id=session_id, run_id=run_id):
        return True

    parent_session_id = str(metadata.get("parent_session_id") or "")
    parent_run_id = str(metadata.get("parent_run_id") or "")
    return store.run_stop_requested(session_id=parent_session_id, run_id=parent_run_id)


def _raise_if_stopped(state: AgentState) -> None:
    if _run_stop_requested(state):
        raise RunStopped("Run was stopped by the user.")


def build_agent_graph(
    *,
    llm: Runnable | None = None,
    registry: ToolRegistry | None = None,
    checkpointer: Any | None = None,
    async_model: bool = False,
):
    tool_registry = registry or create_default_registry()
    model = (llm or create_llm()).bind_tools(tool_registry.schemas())

    def agent_node(state: AgentState) -> dict[str, Any]:
        _raise_if_stopped(state)
        response = model.invoke(messages_with_system_prompt(state))
        _raise_if_stopped(state)
        return _agent_response_update(response)

    async def agent_node_async(state: AgentState) -> dict[str, Any]:
        _raise_if_stopped(state)
        response = await model.ainvoke(messages_with_system_prompt(state))
        _raise_if_stopped(state)
        return _agent_response_update(response)

    def _agent_response_update(response: Any) -> dict[str, Any]:
        return {
            "messages": [response],
            "intermediate_steps": [
                {
                    "node": "agent",
                    "tool_calls": _tool_calls(response),
                }
            ],
        }

    def action_node(state: AgentState) -> dict[str, Any]:
        _raise_if_stopped(state)
        messages = state.get("messages", [])
        if not messages:
            return {"intermediate_steps": [{"node": "action", "status": "skipped"}]}

        approval_store = SQLiteAgentStore()
        tool_messages: list[ToolMessage] = []
        steps: list[dict[str, Any]] = []
        runtime_context = {
            "session_id": state.get("session_id"),
            "agent_id": state.get("agent_id", "default"),
            "metadata": state.get("metadata", {}),
        }
        command_scope = _command_scope(dict(runtime_context.get("metadata") or {}))
        if command_scope == "unrestricted":
            runtime_context["approval_granted"] = True
            runtime_context["command_scope"] = command_scope
        session_id = str(runtime_context.get("session_id") or "")
        agent_id = str(runtime_context.get("agent_id") or "default")
        run_id = str((runtime_context.get("metadata") or {}).get("run_id") or f"run-{session_id}")
        for index, call in enumerate(_tool_calls(messages[-1])):
            _raise_if_stopped(state)
            name = call.get("name", "")
            args = call.get("args") or {}
            tool_call_id = call.get("id") or f"tool_call_{index}"
            _write_stream_event(
                {
                    "type": "tool_start",
                    "tool": name,
                    "tool_call_id": tool_call_id,
                    "args": args if isinstance(args, dict) else {},
                }
            )
            normalized_args = args if isinstance(args, dict) else {}
            decision = evaluate_tool_call(name, normalized_args, command_scope=command_scope)
            if decision.needs_approval:
                try:
                    if session_id:
                        approval_store.ensure_session(session_id, agent_id=agent_id)
                    approval = approval_store.create_approval_request(
                        session_id=session_id,
                        run_id=run_id,
                        tool_call_id=tool_call_id,
                        tool_name=name,
                        args=normalized_args,
                        risk_level=decision.risk_level,
                        summary=decision.summary,
                        metadata={"source": "agent_tool_call"},
                    )
                    _write_stream_event({"type": "approval_pending", "approval": approval})
                    content = approval_pending_tool_message(approval)
                    status = "ok"
                except Exception as exc:  # noqa: BLE001 - approval errors should be visible to the model.
                    content = f"Approval queue failed for {name}: {type(exc).__name__}: {exc}"
                    status = "error"
            else:
                try:
                    content = tool_registry.invoke(
                        name,
                        normalized_args,
                        context=runtime_context,
                    )
                    status = "ok"
                except Exception as exc:  # noqa: BLE001 - tool errors are fed back to the model.
                    content = f"Tool execution failed for {name}: {type(exc).__name__}: {exc}"
                    status = "error"

            _write_stream_event(
                {
                    "type": "tool_end",
                    "tool": name,
                    "tool_call_id": tool_call_id,
                    "status": status,
                    "content": content[:1200],
                }
            )
            if status == "ok":
                special_event = _special_tool_event(name, content)
                if special_event:
                    _write_stream_event(special_event)
            _raise_if_stopped(state)

            tool_messages.append(
                ToolMessage(
                    content=content,
                    name=name,
                    tool_call_id=tool_call_id,
                )
            )
            steps.append(
                {
                    "node": "action",
                    "tool": name,
                    "tool_call_id": tool_call_id,
                    "status": (
                        "pending_approval"
                        if decision.needs_approval and status == "ok"
                        else status
                    ),
                }
            )

        return {"messages": tool_messages, "intermediate_steps": steps}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node_async if async_model else agent_node)
    graph.add_node("action", action_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"action": "action", "end": END})
    graph.add_conditional_edges(
        "action",
        should_continue_after_action,
        {"agent": "agent", "end": END},
    )
    return graph.compile(checkpointer=checkpointer or create_checkpointer())
