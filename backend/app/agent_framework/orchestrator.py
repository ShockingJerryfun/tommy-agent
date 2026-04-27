from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from .agent import build_agent_graph
from .memory import build_thread_config, create_checkpointer
from .store import SQLiteAgentStore
from .tools import (
    ToolRegistry,
    get_current_time,
    list_local_directory,
    list_workspace,
    read_local_file,
    read_workspace_file,
    web_search,
)


def create_subagent_registry() -> ToolRegistry:
    """Read-only tool set for delegated sub-agent tasks."""

    return ToolRegistry(
        tools=(
            get_current_time,
            web_search,
            read_workspace_file,
            list_workspace,
            read_local_file,
            list_local_directory,
        )
    )


def run_delegate_task(
    *,
    task: str,
    target_agent: str,
    reason: str,
    session_id: str,
    parent_run_id: str,
    approval_id: str,
    agent_id: str = "default",
) -> dict[str, Any]:
    """Run a bounded read-only sub-agent and return its final response."""

    if SQLiteAgentStore().run_stop_requested(session_id=session_id, run_id=parent_run_id):
        return {
            "status": "stopped",
            "target_agent": target_agent,
            "thread_id": "",
            "parent_session_id": session_id,
            "parent_run_id": parent_run_id,
            "approval_id": approval_id,
            "result": "",
        }

    thread_id = f"sub-{session_id}-{approval_id}"
    graph = build_agent_graph(
        registry=create_subagent_registry(),
        checkpointer=create_checkpointer(),
    )
    prompt = (
        f"You are a delegated {target_agent} sub-agent. "
        "Work read-only unless a parent approval grants otherwise. "
        "Return a concise result for the parent agent.\n\n"
        f"Reason for delegation: {reason or 'not specified'}\n\n"
        f"Task:\n{task}"
    )
    state = graph.invoke(
        {
            "session_id": thread_id,
            "agent_id": agent_id,
            "metadata": {
                "parent_session_id": session_id,
                "parent_run_id": parent_run_id,
                "approval_id": approval_id,
                "target_agent": target_agent,
            },
            "messages": [HumanMessage(content=prompt)],
        },
        config=build_thread_config(thread_id),
    )
    messages = state.get("messages", [])
    final = ""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.content:
            final = str(message.content)
            break
    return {
        "status": "done",
        "target_agent": target_agent,
        "thread_id": thread_id,
        "parent_session_id": session_id,
        "parent_run_id": parent_run_id,
        "approval_id": approval_id,
        "result": final,
    }
