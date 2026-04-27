from __future__ import annotations

from typing import Any

from langchain_core.runnables import Runnable
from langgraph.graph import END, START, StateGraph

from ..checkpointing import create_checkpointer
from ..llm import create_llm
from ..state import AgentState
from ..tools import ToolRegistry, create_default_registry
from .cognitive import (
    create_critic_node,
    create_planner_node,
    create_pre_run_node,
    create_reflector_node,
)
from .nodes import create_action_node, create_agent_node, create_agent_node_async
from .routing import route_after_agent, route_after_critic


def build_agent_graph(
    *,
    llm: Runnable | None = None,
    registry: ToolRegistry | None = None,
    checkpointer: Any | None = None,
    async_model: bool = False,
):
    """Compile the v2 cognitive graph.

    Topology (S3)::

        START → pre_run → planner → agent
                                    │
                          ┌──tool_calls?──┐
                          ▼ yes          ▼ no
                       action          critic
                          │              │
                          └─→ critic ←───┘
                                  │
                            ┌─continue?─┐
                            ▼ yes      ▼ no / hard-stop
                          agent      reflector → END

    The critic stays in the loop after every turn (including after a
    tool execution) so it can run budget / loop / drift checks before
    the next agent step. The routing distinguishes "just executed a
    tool — let the model speak" from "agent finished without tool
    calls — terminate".

    The ``agent`` and ``action`` nodes are unchanged from S0–S2 so all
    existing tool-routing, approval, and tool-event behaviour is
    preserved. The cognitive wrappers (``pre_run``, ``planner``,
    ``critic``, ``reflector``) own budget enforcement, loop/drift
    detection, citation checks, and terminal reflection.
    """

    tool_registry = registry or create_default_registry()
    model = (llm or create_llm()).bind_tools(tool_registry.schemas())

    graph = StateGraph(AgentState)
    graph.add_node("pre_run", create_pre_run_node())
    graph.add_node("planner", create_planner_node())
    graph.add_node(
        "agent",
        create_agent_node_async(model) if async_model else create_agent_node(model),
    )
    graph.add_node("action", create_action_node(tool_registry))
    graph.add_node("critic", create_critic_node())
    graph.add_node("reflector", create_reflector_node())

    graph.add_edge(START, "pre_run")
    graph.add_edge("pre_run", "planner")
    graph.add_edge("planner", "agent")
    graph.add_conditional_edges(
        "agent",
        route_after_agent,
        {"action": "action", "critic": "critic"},
    )
    graph.add_edge("action", "critic")
    graph.add_conditional_edges(
        "critic",
        route_after_critic,
        {"agent": "agent", "reflector": "reflector"},
    )
    graph.add_edge("reflector", END)

    return graph.compile(checkpointer=checkpointer or create_checkpointer())
