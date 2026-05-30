from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "token",
    "reasoning",
    "message_delta",
    "reasoning_delta",
    "model_start",
    "model_end",
    "model_error",
    "tool_start",
    "tool_end",
    "node_end",
    "context",
    "memory",
    "memory_recall",
    "memory_write",
    "compaction",
    "skill",
    "pact",
    "delegate",
    "approval_pending",
    "approval_resolved",
    "verification_start",
    "verification_end",
    "subagent_start",
    "subagent_end",
    "team_run_started",
    "team_run_completed",
    "team_run_failed",
    "team_task_started",
    "team_task_completed",
    "team_task_failed",
    "team_synthesis_started",
    "team_synthesis_completed",
    "team_synthesis_failed",
    "workflow_run_started",
    "workflow_run_completed",
    "workflow_run_failed",
    "workflow_phase_started",
    "workflow_phase_completed",
    "workflow_phase_failed",
    "workflow_phase_skipped",
    "workflow_worker_completed",
    "workflow_worker_failed",
    "background_run_cancelled",
    "stopped",
    "cancelled",
    "interrupted",
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


def stopped_event(reason: str = "用户已停止本次运行") -> AgentEvent:
    return AgentEvent(type="stopped", data={"status": "stopped", "reason": reason})


def cancelled_event(reason: str = "cancelled") -> AgentEvent:
    return AgentEvent(type="cancelled", data={"status": "cancelled", "reason": reason})


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
    # astream_events surfaces only selected events here; debug/internal events are dropped
    # by design.
    return None


def _extract_reasoning_chunk(message_chunk: Any) -> str:
    """Pull the streaming reasoning fragment from a LangChain chat chunk.

    DeepSeek thinking-mode and OpenAI o-series stream the chain-of-thought
    on ``additional_kwargs.reasoning_content`` (DeepSeek) or
    ``additional_kwargs.reasoning`` (OpenRouter / generic). Both arrive
    chunked, so we just return the new fragment for streaming.
    """
    extras = getattr(message_chunk, "additional_kwargs", None)
    if not isinstance(extras, dict):
        return ""
    for key in ("reasoning_content", "reasoning"):
        value = extras.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            text = value.get("content") or value.get("text")
            if isinstance(text, str) and text:
                return text
    return ""


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
            "token",
            "model_start",
            "model_end",
            "model_error",
            "context",
            "memory",
            "memory_recall",
            "memory_write",
            "compaction",
            "skill",
            "pact",
            "delegate",
            "approval_pending",
            "approval_resolved",
            "subagent_start",
            "subagent_end",
            "stopped",
            "cancelled",
            "interrupted",
        }:
            return AgentEvent(type=custom_type, data={k: v for k, v in data.items() if k != "type"})

    if part_type == "messages":
        message_chunk, metadata = data
        if metadata.get("langgraph_node") != "agent":
            return None
        reasoning = _extract_reasoning_chunk(message_chunk)
        if reasoning:
            return AgentEvent(
                type="reasoning",
                data={"content": reasoning, "node": metadata.get("langgraph_node")},
            )
        content = getattr(message_chunk, "content", "")
        if content:
            return AgentEvent(
                type="token",
                data={"content": content, "node": metadata.get("langgraph_node")},
            )

    if part_type == "updates" and isinstance(data, dict):
        nodes: list[dict[str, Any]] = []
        for node, update in data.items():
            node_payload: dict[str, Any] = {"node": str(node)}
            if isinstance(update, dict):
                node_payload["changed"] = list(update.keys())
                plan = update.get("plan")
                if isinstance(plan, dict):
                    node_payload["plan"] = {
                        "summary": str(plan.get("summary") or "")[:280],
                        "steps": [str(step)[:180] for step in (plan.get("steps") or [])[:4]],
                    }
                intermediate_steps = update.get("intermediate_steps")
                if isinstance(intermediate_steps, list):
                    node_payload["intermediate_steps"] = intermediate_steps[-3:]
            nodes.append(node_payload)
        return AgentEvent(
            type="node_end",
            data={
                "updates": list(data.keys()),
                "nodes": nodes,
            },
        )

    return None
