"""End-to-end smoke test: build_agent_graph compiles + runs a turn.

We fake the LLM and the tool registry so the test stays hermetic. The
goal is to confirm the v2 topology
(``pre_run → planner → agent ⇄ action → critic → reflector → END``)
wires up without errors and that a single agent turn with no tool calls
flows all the way through to the reflector.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from app.agent_framework.graph import build_agent_graph
from app.agent_framework.tool_runtime import ToolRegistry


class _FakeLLM(FakeListChatModel):
    """Minimal fake that ignores ``bind_tools`` (it's a no-op for tests)."""

    def bind_tools(self, *_: Any, **__: Any) -> _FakeLLM:  # noqa: D401
        return self


def _empty_registry() -> ToolRegistry:
    return ToolRegistry(tools=[])


def test_v2_graph_runs_one_turn_to_reflector() -> None:
    from langgraph.checkpoint.memory import InMemorySaver

    fake_llm = _FakeLLM(responses=["The answer is 42."])
    graph = build_agent_graph(
        llm=fake_llm,
        registry=_empty_registry(),
        checkpointer=InMemorySaver(),
    )

    final_state = graph.invoke(
        {
            "messages": [HumanMessage(content="What is the answer?")],
            "session_id": "sess-e2e",
            "agent_id": "default",
            "metadata": {"budget": {"max_turns": 4, "max_wall_seconds": 30}},
        },
        config={"configurable": {"thread_id": "sess-e2e"}},
    )

    # An assistant message was produced.
    ai_messages = [m for m in final_state["messages"] if isinstance(m, AIMessage)]
    assert ai_messages, "the agent must emit at least one AIMessage"
    assert "42" in ai_messages[-1].content

    # Reflection populated by the terminal node.
    reflection = final_state.get("reflection") or {}
    assert reflection.get("terminal_reason") == "completed"
    assert "42" in reflection.get("summary", "")

    # Plan populated by the deterministic planner.
    assert final_state.get("plan", {}).get("summary")

    # Budget started and ticked at least once.
    budget = final_state.get("budget") or {}
    assert budget.get("started_at", 0) > 0
    assert budget.get("turn_count", 0) >= 1

    # Intermediate steps include each cognitive node.
    nodes = {step.get("node") for step in final_state.get("intermediate_steps", [])}
    assert {"pre_run", "planner", "critic", "reflector"}.issubset(nodes)
