"""Unit tests for the S3 cognitive graph scaffolding.

Covers Budget, loop detector, drift detector, citation analyzer, planner,
critic, reflector, and the v2 routing decisions. The graph builder is
exercised end-to-end via a stub LLM that emits a scripted sequence of
``AIMessage`` responses; this is the same pattern the runtime uses in
production but without any external API call.
"""

from __future__ import annotations

import time

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent_framework.graph import (
    Budget,
    analyze_citations,
    approval_is_pending,
    create_critic_node,
    create_planner_node,
    create_pre_run_node,
    create_reflector_node,
    detect_drift,
    detect_loop,
    route_after_agent,
    route_after_critic,
)
from app.agent_framework.state import initial_state

# ----------------------------------------------------------------- Budget


def test_budget_default_caps_and_dict_round_trip() -> None:
    budget = Budget.from_metadata({})
    started = budget.started()

    assert started.max_turns >= 1
    assert started.started_at > 0
    assert started.exhausted is False

    payload = started.as_dict()
    assert payload["max_turns"] == started.max_turns
    assert payload["started_at"] == started.started_at

    restored = Budget.from_dict(payload)
    assert restored.max_turns == started.max_turns
    assert restored.started_at == started.started_at


def test_budget_exhaustion_first_violated_cap_wins() -> None:
    budget = Budget(max_turns=2, max_tool_calls=10).started()
    bumped = budget.tick(new_turns=5, new_tool_calls=1)
    assert bumped.exhausted is True
    assert bumped.exhausted_reason.startswith("turn_cap:")


def test_budget_metadata_overrides_defaults() -> None:
    budget = Budget.from_metadata({"budget": {"max_turns": 3, "max_tool_calls": 5}})
    assert budget.max_turns == 3
    assert budget.max_tool_calls == 5


def test_budget_wall_clock_cap() -> None:
    budget = Budget(max_wall_seconds=0.001)
    started = budget.started()
    time.sleep(0.01)
    bumped = started.tick(new_turns=1)
    assert bumped.exhausted is True
    assert bumped.exhausted_reason.startswith("wall_seconds_cap:")


# --------------------------------------------------------- loop detector


def _ai_with_tool_call(name: str, args: dict, idx: int = 0) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"id": f"call-{name}-{idx}", "name": name, "args": args}],
    )


def test_loop_detector_flags_repeated_tool_args() -> None:
    msgs = [
        HumanMessage(content="What's the weather?"),
        _ai_with_tool_call("weather", {"city": "Shanghai"}, idx=1),
        ToolMessage(content="failed", name="weather", tool_call_id="call-weather-1"),
        _ai_with_tool_call("weather", {"city": "Shanghai"}, idx=2),
        ToolMessage(content="failed", name="weather", tool_call_id="call-weather-2"),
    ]
    signal = detect_loop(msgs)
    assert signal.detected is True
    assert signal.count >= 2
    assert signal.repeated_call["name"] == "weather"


def test_loop_detector_quiet_for_distinct_calls() -> None:
    msgs = [
        _ai_with_tool_call("a", {"x": 1}, idx=1),
        _ai_with_tool_call("b", {"y": 2}, idx=2),
        _ai_with_tool_call("c", {"z": 3}, idx=3),
    ]
    signal = detect_loop(msgs)
    assert signal.detected is False


# -------------------------------------------------------- drift detector


def test_drift_detector_counts_consecutive_tool_errors() -> None:
    steps = [
        {"node": "agent", "status": "ok"},
        {"node": "action", "tool": "x", "status": "error"},
        {"node": "action", "tool": "x", "status": "error"},
        {"node": "action", "tool": "x", "status": "error"},
    ]
    signal = detect_drift(steps)
    assert signal.detected is True
    assert signal.tool_error_streak == 3


def test_drift_detector_resets_on_success() -> None:
    steps = [
        {"node": "action", "status": "error"},
        {"node": "action", "status": "error"},
        {"node": "action", "status": "ok"},
        {"node": "action", "status": "error"},
    ]
    signal = detect_drift(steps)
    assert signal.detected is False


# ------------------------------------------------------- citation analyzer


def test_citation_required_when_web_search_used_without_url() -> None:
    msgs = [
        HumanMessage(content="What's the latest on Mars rovers?"),
        AIMessage(
            content="",
            tool_calls=[{"id": "1", "name": "web_search", "args": {"query": "mars"}}],
        ),
        ToolMessage(content="results", name="web_search", tool_call_id="1"),
        AIMessage(content="The Perseverance rover is exploring Jezero Crater."),
    ]
    signal = analyze_citations(msgs)
    assert signal.required is True
    assert signal.satisfied is False
    assert "web_search" in signal.missing_for_tools


def test_citation_satisfied_when_url_present() -> None:
    msgs = [
        AIMessage(content="", tool_calls=[{"id": "1", "name": "web_search", "args": {}}]),
        ToolMessage(content="results", name="web_search", tool_call_id="1"),
        AIMessage(content="See https://nasa.gov/perseverance for details."),
    ]
    signal = analyze_citations(msgs)
    assert signal.required is True
    assert signal.satisfied is True


def test_citation_not_required_for_local_tools_only() -> None:
    msgs = [
        AIMessage(content="", tool_calls=[{"id": "1", "name": "list_files", "args": {}}]),
        ToolMessage(content="files", name="list_files", tool_call_id="1"),
        AIMessage(content="Listed your files."),
    ]
    signal = analyze_citations(msgs)
    assert signal.required is False


# ----------------------------------------------------------- node tests


def test_pre_run_node_stamps_budget() -> None:
    state = initial_state(session_id="sess-1")
    state["messages"] = [HumanMessage(content="hi")]
    update = create_pre_run_node()(state)
    budget = update["budget"]
    assert budget["started_at"] > 0
    assert budget["turn_count"] == 0
    assert budget["max_turns"] >= 1


def test_pre_run_node_idempotent_on_resume() -> None:
    state = initial_state(session_id="sess-1")
    state["budget"] = {
        "started_at": 12345.67,
        "max_turns": 8,
        "max_tool_calls": 10,
        "max_wall_seconds": 30,
        "max_total_chars": 5000,
        "turn_count": 3,
        "tool_call_count": 2,
        "total_chars": 100,
    }
    update = create_pre_run_node()(state)
    assert update["budget"]["started_at"] == 12345.67
    assert update["budget"]["turn_count"] == 3


def test_planner_extracts_steps_and_caches_by_user_message() -> None:
    state = initial_state(session_id="sess-1")
    state["messages"] = [
        HumanMessage(
            content=(
                "Help me plan a release. Update the docs. Notify the team. Schedule the deploy."
            )
        )
    ]
    planner = create_planner_node()
    first = planner(state)
    assert first["plan"]["steps"], "planner should produce at least one step"
    assert "release" in first["plan"]["summary"].lower()

    # Re-run with the cached plan stamped on state — should be a no-op.
    state["plan"] = first["plan"]
    second = planner(state)
    assert second == {}


def test_critic_writes_directives_for_loop_drift_citation() -> None:
    state = initial_state(session_id="sess-1")
    state["messages"] = [
        HumanMessage(content="What's new on Mars?"),
        AIMessage(
            content="",
            tool_calls=[{"id": "1", "name": "web_search", "args": {"query": "mars"}}],
        ),
        ToolMessage(content="errored", name="web_search", tool_call_id="1"),
        _ai_with_tool_call("web_search", {"query": "mars"}, idx=2),
        ToolMessage(content="errored", name="web_search", tool_call_id="call-web_search-2"),
        _ai_with_tool_call("web_search", {"query": "mars"}, idx=3),
        ToolMessage(content="errored", name="web_search", tool_call_id="call-web_search-3"),
        AIMessage(content="No clear citations available."),
    ]
    state["intermediate_steps"] = [
        {"node": "action", "status": "error", "tool": "web_search"},
        {"node": "action", "status": "error", "tool": "web_search"},
        {"node": "action", "status": "error", "tool": "web_search"},
    ]
    state["budget"] = Budget.from_metadata({}).started().as_dict()

    update = create_critic_node()(state)
    kinds = {d["kind"] for d in update.get("critic_directives", [])}
    assert "loop" in kinds
    assert "drift" in kinds
    assert "citation" in kinds
    assert update["loop_signals"]["detected"] is True
    assert update["drift_signals"]["detected"] is True
    assert update["citation_signals"]["required"] is True


def test_critic_marks_budget_exhaustion() -> None:
    state = initial_state(session_id="sess-1")
    state["messages"] = [
        HumanMessage(content="hi"),
        AIMessage(content="ok"),
    ]
    state["budget"] = (
        Budget(max_turns=0, max_tool_calls=0, max_wall_seconds=999, max_total_chars=999)
        .started()
        .as_dict()
    )
    update = create_critic_node()(state)
    assert update["budget"]["exhausted"] is True


def test_reflector_summarises_terminal_state() -> None:
    state = initial_state(session_id="sess-1")
    state["messages"] = [
        HumanMessage(content="hi"),
        AIMessage(content="The answer is 42."),
    ]
    state["budget"] = Budget.from_metadata({}).started().as_dict()
    state["loop_signals"] = {"detected": False}
    update = create_reflector_node()(state)
    reflection = update["reflection"]
    assert "42" in reflection["summary"]
    assert reflection["terminal_reason"] == "completed"


# ----------------------------------------------------- routing decisions


def test_route_after_agent_picks_action_when_tool_calls_present() -> None:
    state = initial_state(session_id="sess-1")
    state["messages"] = [_ai_with_tool_call("x", {}, idx=1)]
    assert route_after_agent(state) == "action"


def test_route_after_agent_picks_critic_when_no_tool_calls() -> None:
    state = initial_state(session_id="sess-1")
    state["messages"] = [AIMessage(content="done")]
    assert route_after_agent(state) == "critic"


def test_route_after_critic_terminates_on_budget_exhaustion() -> None:
    state = initial_state(session_id="sess-1")
    state["messages"] = [AIMessage(content="hi")]
    state["budget"] = {"exhausted": True, "exhausted_reason": "turn_cap:1"}
    assert route_after_critic(state) == "reflector"


def test_route_after_critic_terminates_on_loop_signal() -> None:
    state = initial_state(session_id="sess-1")
    state["messages"] = [AIMessage(content="hi")]
    state["loop_signals"] = {"detected": True}
    assert route_after_critic(state) == "reflector"


def test_route_after_critic_continues_after_action() -> None:
    """When the run is healthy and the last AI emitted no tool calls, the
    critic is treated as terminal so the run finishes cleanly."""

    state = initial_state(session_id="sess-1")
    state["messages"] = [AIMessage(content="final answer")]
    state["budget"] = {"exhausted": False}
    state["loop_signals"] = {"detected": False}
    state["drift_signals"] = {"detected": False}
    assert route_after_critic(state) == "reflector"


def test_route_after_critic_loops_back_when_last_message_is_tool() -> None:
    """Regression: after ``action`` ran, the tail is a ToolMessage. The
    critic must send the run BACK to ``agent`` so the model can read the
    tool output and produce its final answer — not terminate prematurely.
    """

    state = initial_state(session_id="sess-1")
    state["messages"] = [
        HumanMessage(content="search for X"),
        _ai_with_tool_call("web_search", {"query": "X"}, idx=1),
        ToolMessage(content="tool result", name="web_search", tool_call_id="call-web_search-1"),
    ]
    state["budget"] = {"exhausted": False}
    state["loop_signals"] = {"detected": False}
    state["drift_signals"] = {"detected": False}
    assert route_after_critic(state) == "agent"


def test_route_after_critic_reflects_when_approval_is_pending() -> None:
    state = initial_state(session_id="sess-1")
    state["messages"] = [
        HumanMessage(content="run pwd"),
        _ai_with_tool_call("run_shell_command", {"command": "pwd"}, idx=1),
        ToolMessage(
            content="queued for approval",
            name="run_shell_command",
            tool_call_id="call-run_shell_command-1",
        ),
    ]
    state["budget"] = {"exhausted": False}
    state["loop_signals"] = {"detected": False}
    state["drift_signals"] = {"detected": False}
    state["intermediate_steps"] = [
        {"node": "action", "tool": "run_shell_command", "status": "pending_approval"}
    ]

    assert approval_is_pending(state) is True
    assert route_after_critic(state) == "reflector"
