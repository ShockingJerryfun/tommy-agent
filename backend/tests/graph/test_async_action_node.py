from __future__ import annotations

import asyncio
import time

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from app.agent_framework.graph.nodes import create_action_node_async
from app.agent_framework.tool_modules.registry import ToolRegistry


@tool
def slow_echo() -> str:
    """Return a static value after a short blocking wait."""
    time.sleep(0.2)
    return "ok"


@pytest.mark.asyncio
async def test_async_action_node_runs_blocking_tool_off_event_loop() -> None:
    node = create_action_node_async(ToolRegistry(tools=(slow_echo,)))
    state = {
        "session_id": "session-1",
        "agent_id": "default",
        "metadata": {"run_id": "run-1"},
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "slow_echo", "args": {}, "id": "call-1"}],
            )
        ],
    }

    started = time.perf_counter()
    task = asyncio.create_task(node(state))
    await asyncio.sleep(0.05)

    assert time.perf_counter() - started < 0.15
    assert task.done() is False
    result = await task
    assert result["messages"][0].content == "ok"
    assert result["intermediate_steps"][0]["status"] == "ok"
