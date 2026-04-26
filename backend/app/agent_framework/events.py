from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field


EventType = Literal[
    "token",
    "tool_start",
    "tool_end",
    "node_end",
    "memory",
    "compaction",
    "skill",
    "pact",
    "delegate",
    "approval_pending",
    "approval_resolved",
    "subagent_start",
    "subagent_end",
    "error",
    "done",
]


class AgentEvent(BaseModel):
    type: EventType = Field(..., description="Client-facing event type.")
    data: dict[str, Any] = Field(default_factory=dict)


def format_sse(event: AgentEvent) -> str:
    payload = event.model_dump(mode="json")
    return f"event: {event.type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def done_event() -> AgentEvent:
    return AgentEvent(type="done", data={"status": "done"})


def error_event(error: Exception | str) -> AgentEvent:
    return AgentEvent(type="error", data={"message": str(error)})


def map_langgraph_event(event: dict[str, Any]) -> AgentEvent | None:
    """Map noisy LangGraph v2 events into a small UI-safe event vocabulary."""
    kind = event.get("event")
    metadata = event.get("metadata") or {}
    data = event.get("data") or {}
    name = event.get("name")

    if kind == "on_chat_model_stream":
        chunk = data.get("chunk")
        content = getattr(chunk, "content", "")
        if not content:
            return None
        return AgentEvent(
            type="token",
            data={
                "content": content,
                "node": metadata.get("langgraph_node"),
                "run_id": event.get("run_id"),
            },
        )

    if kind == "on_tool_start":
        return AgentEvent(
            type="tool_start",
            data={
                "tool": name,
                "input": data.get("input"),
                "run_id": event.get("run_id"),
            },
        )

    if kind == "on_tool_end":
        return AgentEvent(
            type="tool_end",
            data={
                "tool": name,
                "output": str(data.get("output", ""))[:1200],
                "run_id": event.get("run_id"),
            },
        )

    if kind == "on_chain_end" and metadata.get("langgraph_node"):
        return AgentEvent(
            type="node_end",
            data={
                "node": metadata.get("langgraph_node"),
                "name": name,
                "run_id": event.get("run_id"),
            },
        )

    # LangGraph custom stream writer events arrive via stream_mode="custom".
    # astream_events surfaces only selected events here; debug/internal events are dropped by design.
    return None


def map_stream_part(part: tuple[str, Any]) -> AgentEvent | None:
    """Map a LangGraph astream tuple (mode, data) to a UI-safe AgentEvent.

    When astream is called with stream_mode as a list, LangGraph yields
    (mode_str, data) tuples — not dicts. This function handles that contract.
    """
    if not isinstance(part, tuple) or len(part) != 2:
        return None
    part_type, data = part

    if part_type == "custom" and isinstance(data, dict):
        custom_type = data.get("type")
        if custom_type in {
            "tool_start",
            "tool_end",
            "memory",
            "compaction",
            "skill",
            "pact",
            "delegate",
            "approval_pending",
            "approval_resolved",
            "subagent_start",
            "subagent_end",
        }:
            return AgentEvent(type=custom_type, data={k: v for k, v in data.items() if k != "type"})

    if part_type == "messages":
        message_chunk, metadata = data
        if metadata.get("langgraph_node") != "agent":
            return None
        content = getattr(message_chunk, "content", "")
        if content:
            return AgentEvent(
                type="token",
                data={"content": content, "node": metadata.get("langgraph_node")},
            )

    if part_type == "updates" and isinstance(data, dict):
        return AgentEvent(type="node_end", data={"updates": list(data.keys())})

    return None
