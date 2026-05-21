from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.runnables import Runnable
from langgraph.config import get_stream_writer

from ..prompt_context import messages_with_context
from ..runtime.model_options import bind_runtime_model_options
from ..state import AgentState
from ..storage import get_agent_store
from ..tool_runtime import ToolRegistry, ToolRuntime
from ..tool_runtime.approvals import approval_pending_tool_message, evaluate_tool_call
from .exceptions import RunStopped
from .routing import raise_if_stopped, run_stop_requested, tool_calls


def write_stream_event(payload: dict[str, Any]) -> None:
    try:
        writer = get_stream_writer()
    except RuntimeError:
        return
    writer(payload)


def special_tool_event(name: str, content: str) -> dict[str, Any] | None:
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


def command_scope(metadata: dict[str, Any]) -> str:
    frontend_settings = metadata.get("frontend_settings")
    if isinstance(frontend_settings, dict):
        scope = str(frontend_settings.get("commandScope") or "unrestricted")
        if scope in {"restricted", "unrestricted"}:
            return scope
    return "unrestricted"


def agent_response_update(response: Any) -> dict[str, Any]:
    return {
        "messages": [response],
        "intermediate_steps": [
            {
                "node": "agent",
                "tool_calls": tool_calls(response),
            }
        ],
    }


def create_agent_node(
    model: Runnable,
    tool_registry: ToolRegistry | None = None,
) -> Callable[[AgentState], dict[str, Any]]:
    def agent_node(state: AgentState) -> dict[str, Any]:
        raise_if_stopped(state)
        messages, rendered_context = messages_with_context(
            _state_with_tool_inventory(state, tool_registry)
        )
        write_stream_event({"type": "context", **rendered_context.snapshot()})
        runtime_model = bind_runtime_model_options(model, state.get("metadata"))
        response = runtime_model.invoke(messages)
        raise_if_stopped(state)
        return agent_response_update(response)

    return agent_node


def create_agent_node_async(model: Runnable, tool_registry: ToolRegistry | None = None):
    async def agent_node_async(state: AgentState) -> dict[str, Any]:
        raise_if_stopped(state)
        messages, rendered_context = messages_with_context(
            _state_with_tool_inventory(state, tool_registry)
        )
        write_stream_event({"type": "context", **rendered_context.snapshot()})
        runtime_model = bind_runtime_model_options(model, state.get("metadata"))
        response = await runtime_model.ainvoke(messages)
        raise_if_stopped(state)
        return agent_response_update(response)

    return agent_node_async


def _state_with_tool_inventory(
    state: AgentState,
    tool_registry: ToolRegistry | None,
) -> AgentState:
    if tool_registry is None:
        return state
    metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
    if isinstance(metadata.get("available_tools"), list):
        return state
    return {
        **state,
        "metadata": {
            **metadata,
            "available_tools": sorted(str(name) for name in tool_registry.by_name),
        },
    }


def create_action_node(tool_registry: ToolRegistry) -> Callable[[AgentState], dict[str, Any]]:
    runtime = ToolRuntime(tool_registry)

    def action_node(state: AgentState) -> dict[str, Any]:
        raise_if_stopped(state)
        messages = state.get("messages", [])
        if not messages:
            return {"intermediate_steps": [{"node": "action", "status": "skipped"}]}

        approval_store = get_agent_store()
        tool_messages: list[ToolMessage] = []
        steps: list[dict[str, Any]] = []
        runtime_context = {
            "session_id": state.get("session_id"),
            "agent_id": state.get("agent_id", "default"),
            "metadata": state.get("metadata", {}),
        }
        scope = command_scope(dict(runtime_context.get("metadata") or {}))
        if scope == "unrestricted":
            runtime_context["approval_granted"] = True
            runtime_context["command_scope"] = scope
        session_id = str(runtime_context.get("session_id") or "")
        agent_id = str(runtime_context.get("agent_id") or "default")
        run_id = str((runtime_context.get("metadata") or {}).get("run_id") or f"run-{session_id}")
        all_calls = list(tool_calls(messages[-1]))
        completed_ids: set[str] = set()
        stopped = False
        try:
            for index, call in enumerate(all_calls):
                raise_if_stopped(state)
                name = call.get("name", "")
                args = call.get("args") or {}
                tool_call_id = call.get("id") or f"tool_call_{index}"
                write_stream_event(
                    {
                        "type": "tool_start",
                        "tool": name,
                        "tool_call_id": tool_call_id,
                        "args": args if isinstance(args, dict) else {},
                    }
                )
                normalized_args = args if isinstance(args, dict) else {}
                decision = evaluate_tool_call(name, normalized_args, command_scope=scope)
                tool_message_status: str
                artifact_meta: dict[str, Any] | None = None
                if decision.denied:
                    content = json.dumps(
                        {
                            "status": "error",
                            "error": {
                                "code": "permission_denied",
                                "message": decision.deny_reason
                                or "Tool call denied by permission policy.",
                                "details": {"tool": name, "risk": decision.risk_level},
                            },
                        },
                        ensure_ascii=False,
                    )
                    tool_message_status = "error"
                elif decision.needs_approval:
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
                        write_stream_event({"type": "approval_pending", "approval": approval})
                        content = approval_pending_tool_message(approval)
                        tool_message_status = "pending_approval"
                    except Exception as exc:  # noqa: BLE001 - approval errors are visible to the model.
                        content = f"Approval queue failed for {name}: {type(exc).__name__}: {exc}"
                        tool_message_status = "error"
                else:
                    exec_context = dict(runtime_context)
                    exec_context["approval_granted"] = True
                    result = runtime.execute(
                        name,
                        normalized_args,
                        tool_call_id=tool_call_id,
                        context=exec_context,
                        store=approval_store,
                        session_id=session_id or None,
                        run_id=run_id,
                        command_scope=scope,
                        persist=False,
                    )
                    content = result.content
                    tool_message_status = result.status
                    if result.artifact is not None:
                        artifact_meta = {
                            "artifact_id": result.artifact.artifact_id,
                            "size_bytes": result.artifact.size_bytes,
                            "spilled": True,
                        }

                write_stream_event(
                    {
                        "type": "tool_end",
                        "tool": name,
                        "tool_call_id": tool_call_id,
                        "status": tool_message_status,
                        "content": content[:1200],
                        **({"artifact": artifact_meta} if artifact_meta else {}),
                    }
                )
                if tool_message_status == "ok":
                    event = special_tool_event(name, content)
                    if event:
                        write_stream_event(event)

                tool_messages.append(
                    ToolMessage(
                        content=content,
                        name=name,
                        tool_call_id=tool_call_id,
                    )
                )
                completed_ids.add(tool_call_id)
                step: dict[str, Any] = {
                    "node": "action",
                    "tool": name,
                    "tool_call_id": tool_call_id,
                    "status": tool_message_status,
                }
                if artifact_meta is not None:
                    step["artifact_id"] = artifact_meta["artifact_id"]
                    step["spilled"] = True
                steps.append(step)
                if run_stop_requested(state):
                    stopped = True
                    break
        except RunStopped:
            stopped = True

        # Fill placeholder ToolMessages for any tool_calls that didn't execute,
        # so the checkpoint never has orphaned tool_calls without responses.
        for idx, call in enumerate(all_calls):
            cid = call.get("id") or f"tool_call_{idx}"
            if cid not in completed_ids:
                tool_messages.append(
                    ToolMessage(
                        content="Tool execution was cancelled.",
                        name=call.get("name", ""),
                        tool_call_id=cid,
                    )
                )
                steps.append({
                    "node": "action",
                    "tool": call.get("name", ""),
                    "tool_call_id": cid,
                    "status": "cancelled",
                })

        if stopped:
            raise RunStopped("Run was stopped by the user.")

        return {"messages": tool_messages, "intermediate_steps": steps}

    return action_node
