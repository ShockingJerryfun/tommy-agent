"""Cognitive nodes — pre_run / planner / critic / reflector.

The classic ``agent`` (LLM call) and ``action`` (tool dispatch) nodes
remain unchanged in :mod:`graph.nodes`; this module wraps them with a
deliberate cognitive loop:

::

    START
      ↓
    pre_run  ← initialise budget, stamp start time, copy plan slot
      ↓
    planner  ← deterministic light planner (LLM-driven planner is S5+)
      ↓
    agent    ← (existing) LLM with bound tools
      ↓ tool_calls?
      ┌─────────────────┐
      │ no              │ yes
      ▼                 ▼
    critic            action
      ↓                 ↓
    reflector ←────── critic
      ↓
    END

The critic owns budget enforcement, loop+drift detection, and citation
checks. It either lets the run continue (back to ``agent``) or hard-stops
into the reflector. The reflector writes a terminal audit row — the
heavyweight memory reflector lives in :mod:`memory_platform.pipelines`
and is invoked separately by the run pipeline / pre-compact hook.

All cognitive prompts target DeepSeek v4 Pro (the model bound at
:func:`build_agent_graph`); we don't make a separate model call here in
S3 — the planner and critic are deterministic so the cognitive loop is
free to run on every turn. S5+ can swap the planner for an LLM-backed
one without changing the graph topology.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from ..state import AgentState
from .budget import Budget
from .detectors import analyze_citations, detect_drift, detect_loop
from .routing import raise_if_stopped, tool_calls


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


# ----------------------------------------------------------------- pre_run


def create_pre_run_node() -> Callable[[AgentState], dict[str, Any]]:
    """Stamp the budget at the start of a run.

    Idempotent: re-running pre_run after a checkpointed restore keeps
    the original ``started_at`` and prior counters.
    """

    def pre_run_node(state: AgentState) -> dict[str, Any]:
        raise_if_stopped(state)
        existing_budget = state.get("budget") or {}
        if existing_budget.get("started_at"):
            budget = Budget.from_dict(existing_budget)
        else:
            metadata = state.get("metadata") or {}
            budget = Budget.from_metadata(metadata if isinstance(metadata, dict) else {}).started()

        return {
            "budget": budget.as_dict(),
            "intermediate_steps": [
                {
                    "node": "pre_run",
                    "status": "ok",
                    "budget_caps": {
                        "max_turns": budget.max_turns,
                        "max_tool_calls": budget.max_tool_calls,
                        "max_wall_seconds": budget.max_wall_seconds,
                        "max_total_chars": budget.max_total_chars,
                    },
                    "created_at": _utc_now(),
                }
            ],
        }

    return pre_run_node


# ----------------------------------------------------------------- planner


def _last_user_message(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content or "")
        msg_type = getattr(message, "type", "")
        if msg_type == "human":
            return str(getattr(message, "content", "") or "")
    return ""


def create_planner_node() -> Callable[[AgentState], dict[str, Any]]:
    """Deterministic, lightweight planner.

    Extracts the user's most recent ask and stores a structured plan
    skeleton on ``state.plan``. The plan is a *suggestion* for the
    reasoner — never a hard constraint — so the model can ignore it
    when the user query needs no decomposition.

    A plan is *only* re-written when the user message has changed (the
    plan caches by ``user_message_hash``), so the same multi-turn
    conversation reuses the original plan instead of jittering it.
    """

    def planner_node(state: AgentState) -> dict[str, Any]:
        raise_if_stopped(state)
        messages = state.get("messages", []) or []
        user_message = _last_user_message(messages)
        if not user_message:
            return {}

        existing_plan = state.get("plan") or {}
        message_hash = str(hash(user_message))
        if existing_plan.get("user_message_hash") == message_hash:
            return {}

        # Deterministic step heuristic: split on sentence terminators and
        # keep up to four leading clauses as candidate steps. Cheap, but
        # the structure means the agent's system prompt can render a
        # "plan" section consistently.
        snippets: list[str] = []
        for chunk in user_message.replace("\n", " ").split("。"):
            for part in chunk.split("."):
                cleaned = " ".join(part.split())
                if cleaned:
                    snippets.append(cleaned)
        steps = snippets[:4] if snippets else [user_message[:200]]

        plan = {
            "summary": user_message[:280],
            "steps": steps,
            "expected_tools": [],
            "user_message_hash": message_hash,
            "created_at": _utc_now(),
            "node": "planner",
        }
        return {
            "plan": plan,
            "intermediate_steps": [
                {
                    "node": "planner",
                    "status": "ok",
                    "step_count": len(steps),
                    "created_at": _utc_now(),
                }
            ],
        }

    return planner_node


# ------------------------------------------------------------------ critic


def _count_chars(message: Any) -> int:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        return sum(len(str(part)) for part in content)
    return len(str(content or ""))


def create_critic_node() -> Callable[[AgentState], dict[str, Any]]:
    """Run the post-turn checks: budget, loop, drift, citations.

    Writes signals to state and may emit ``critic_directives`` that the
    next agent turn will see (via the ``critic_feedback`` prompt
    section). When a hard-stop condition fires (budget exhausted, loop
    detected, drift sustained), the routing function
    :func:`should_continue_after_critic` will redirect to the reflector.
    """

    def critic_node(state: AgentState) -> dict[str, Any]:
        raise_if_stopped(state)
        messages = state.get("messages", []) or []
        intermediate_steps = state.get("intermediate_steps", []) or []

        # Tally the most recent agent turn for budget accounting. We look
        # at the last AI message and the count of tool calls inside it.
        new_chars = 0
        new_tool_calls = 0
        last_ai: AIMessage | None = None
        for message in reversed(messages):
            if isinstance(message, AIMessage):
                last_ai = message
                new_chars = _count_chars(message)
                new_tool_calls = len(tool_calls(message))
                break

        budget = Budget.from_dict(state.get("budget") or {}).tick(
            new_turns=1,
            new_tool_calls=new_tool_calls,
            new_chars=new_chars,
            note="critic_tick",
        )

        loop_signal = detect_loop(messages)
        drift_signal = detect_drift(intermediate_steps)
        citation_signal = analyze_citations(messages)

        directives: list[dict[str, Any]] = []
        now = _utc_now()
        if loop_signal.detected:
            directives.append(
                {
                    "kind": "loop",
                    "message": (
                        "你似乎在重复调用同一个工具且参数相近。请总结当前已知信息，"
                        "在不再调用工具的前提下直接给出答案，或换一个完全不同的策略。"
                    ),
                    "metadata": loop_signal.as_dict(),
                    "node": "critic",
                    "created_at": now,
                }
            )
        if drift_signal.detected:
            directives.append(
                {
                    "kind": "drift",
                    "message": (
                        "连续工具调用失败已超过阈值，请停止重复尝试，向用户说明遇到的"
                        "问题并请求澄清，或回退到不依赖该工具的方案。"
                    ),
                    "metadata": drift_signal.as_dict(),
                    "node": "critic",
                    "created_at": now,
                }
            )
        if citation_signal.required and not citation_signal.satisfied:
            tools_str = ", ".join(citation_signal.missing_for_tools) or "web_search"
            directives.append(
                {
                    "kind": "citation",
                    "message": (
                        f"你引用了来自 {tools_str} 的网络信息，但回答中没有提供任何"
                        f"链接或出处，请在最终答案中以 Markdown 链接 [来源](URL) 的"
                        f"形式补充权威出处。"
                    ),
                    "metadata": citation_signal.as_dict(),
                    "node": "critic",
                    "created_at": now,
                }
            )

        update: dict[str, Any] = {
            "budget": budget.as_dict(),
            "loop_signals": loop_signal.as_dict(),
            "drift_signals": drift_signal.as_dict(),
            "citation_signals": citation_signal.as_dict(),
            "intermediate_steps": [
                {
                    "node": "critic",
                    "status": "ok",
                    "budget_exhausted": budget.exhausted,
                    "loop_detected": loop_signal.detected,
                    "drift_detected": drift_signal.detected,
                    "citation_satisfied": (
                        citation_signal.satisfied if citation_signal.required else True
                    ),
                    "directive_count": len(directives),
                    "last_ai_chars": _count_chars(last_ai) if last_ai else 0,
                    "created_at": now,
                }
            ],
        }
        if directives:
            update["critic_directives"] = directives
        return update

    return critic_node


# --------------------------------------------------------------- reflector


def create_reflector_node() -> Callable[[AgentState], dict[str, Any]]:
    """Terminal reflector — records a final summary on the run.

    The heavy memory reflector (which proposes new memory items) lives
    in :mod:`memory_platform.pipelines` and is wired into the run
    pipeline + on_pre_compact hook (S2). This terminal node only
    captures the *graph-level* close-out: budget snapshot, signals,
    and the assistant's final content for downstream auditing.
    """

    def reflector_node(state: AgentState) -> dict[str, Any]:
        raise_if_stopped(state)
        messages = state.get("messages", []) or []
        budget = Budget.from_dict(state.get("budget") or {})
        loop_signal = state.get("loop_signals") or {}
        drift_signal = state.get("drift_signals") or {}
        citation_signal = state.get("citation_signals") or {}

        last_assistant_text = ""
        for message in reversed(messages):
            if isinstance(message, AIMessage):
                last_assistant_text = str(message.content or "")
                break

        terminal_reason = "completed"
        if budget.exhausted:
            terminal_reason = f"budget_exhausted:{budget.exhausted_reason}"
        elif loop_signal.get("detected"):
            terminal_reason = f"loop_detected:{loop_signal.get('reason')}"
        elif drift_signal.get("detected"):
            terminal_reason = f"drift_detected:{drift_signal.get('reason')}"

        reflection = {
            "summary": last_assistant_text[:600],
            "terminal_reason": terminal_reason,
            "budget_snapshot": budget.as_dict(),
            "loop_signal": loop_signal,
            "drift_signal": drift_signal,
            "citation_signal": citation_signal,
            "created_at": _utc_now(),
        }
        return {
            "reflection": reflection,
            "intermediate_steps": [
                {
                    "node": "reflector",
                    "status": "ok",
                    "terminal_reason": terminal_reason,
                    "created_at": _utc_now(),
                }
            ],
        }

    return reflector_node
