from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .budgets import REQUIRED_SECTIONS, SECTION_BUDGETS, SECTION_MIN_CHARS
from .pact import pact_markdown
from .types import Section

logger = logging.getLogger(__name__)

RENDER_ORDER: dict[str, int] = {
    "runtime": 10,
    "soul": 20,
    "user": 30,
    "dreams": 35,
    "memory_boundary": 40,
    "tool_use": 50,
    "context_pact": 60,
    "session_summary": 70,
    "session_metadata": 75,
    "working_directory": 78,
    "curated_memory": 80,
    "retrieved_memory": 85,
    "skill_index": 89,
    "selected_skills": 90,
    "extracted_context": 95,
    "plan": 32,
    "critic_feedback": 36,
    "subagent_summary": 88,
    "team_summary": 87,
}


def build_section_drafts(
    *,
    store: Any,
    agent_root: Path,
    session_id: str,
    session: dict[str, Any] | None,
    metadata: dict[str, Any],
    working_directory: str,
    context_pact: dict[str, Any],
    available_skill_index: str,
    selected_skills: str,
    recalled_memories: list[dict[str, Any]],
    extracted_context: Any,
    current_time: str,
    plan: dict[str, Any] | None = None,
    critic_directives: list[dict[str, Any]] | None = None,
) -> list[Section]:
    runtime_body = "\n".join(
        [
            "You are running inside a LangGraph-first agent framework.",
            f"Current UTC time: {current_time}",
            f"Session ID: {session_id or 'unknown'}",
        ]
    )
    tool_use_body = "\n\n".join(
        [
            (
                "Use tools when they materially improve the answer. If a tool fails, "
                "inspect the error and retry with corrected arguments when appropriate."
            ),
            (
                "Use web_search for current external facts, documentation, news, prices, "
                "or claims that need citation. Prefer small max_results, fast "
                "search_depth, no raw content, and targeted domains/time ranges to "
                "save context."
            ),
            (
                "When a working directory is selected, treat it as the default project "
                "scope for conversation context, file tools, and shell commands. Do not "
                "read, write, or run commands outside it unless the user explicitly "
                "changes the working directory."
            ),
            (
                "Local file tools may read, list, and write files under the active "
                "working directory or configured local file access root. Use exact paths "
                "and avoid unnecessary edits."
            ),
        ]
    )
    memory_boundary_body = (
        "Do not claim you have permanently remembered something unless the runtime "
        "reports a confirmed memory write. If the user asks you to remember something, "
        "acknowledge that it has been proposed for confirmation.\n\n"
        "Markdown files are Static Profile from Markdown: SOUL.md, USER.md, "
        "DREAMS.md, and optionally MEMORY.md seed/export content. PostgreSQL "
        "memories are Active Memory from PostgreSQL and are the runtime source "
        "of truth for confirmed factual long-term memory.\n\n"
        "Conflict policy: profile/personality conflicts are resolved in favor of "
        "SOUL.md and USER.md static settings; runtime factual-memory conflicts are "
        "resolved in favor of PostgreSQL active memories. Prompt snapshots keep "
        "these sources in separate sections for debug inspection."
    )

    return [
        make_section("runtime", "Runtime", runtime_body, source="runtime", priority=100),
        make_section(
            "soul",
            "Static Profile from Markdown - SOUL",
            read_optional(agent_root / "SOUL.md"),
            source=str(agent_root / "SOUL.md"),
            priority=95,
        ),
        make_section(
            "user",
            "Static Profile from Markdown - USER",
            read_optional(agent_root / "USER.md"),
            source=str(agent_root / "USER.md"),
            priority=85,
        ),
        make_section(
            "dreams",
            "Static Profile from Markdown - DREAMS",
            read_optional(agent_root / "DREAMS.md"),
            source=str(agent_root / "DREAMS.md"),
            priority=82,
        ),
        make_section(
            "memory_boundary",
            "Memory Boundary",
            memory_boundary_body,
            source="runtime.memory_policy",
            priority=95,
        ),
        make_section(
            "tool_use", "Tool Use", tool_use_body, source="runtime.tool_policy", priority=90
        ),
        make_section(
            "context_pact",
            "Context Pact",
            pact_markdown(context_pact),
            source="postgres.context_pacts",
            priority=70,
        ),
        make_section(
            "session_summary",
            "Session Summary",
            str((session or {}).get("summary") or "No summary yet."),
            source="postgres.sessions.summary",
            priority=90,
        ),
        make_section(
            "session_metadata",
            "Session Metadata",
            str(metadata or {}),
            source="run.metadata",
            priority=50,
        ),
        make_section(
            "working_directory",
            "Working Directory",
            working_directory
            or (
                "No working directory selected. Use the configured workspace root "
                "when tools need files."
            ),
            source="frontend.settings.workingDirectory",
            priority=70,
        ),
        make_section(
            "curated_memory",
            "Static Profile from Markdown - MEMORY Seed/Profile",
            read_optional(agent_root / "MEMORY.md"),
            source=str(agent_root / "MEMORY.md"),
            priority=80,
        ),
        make_section(
            "retrieved_memory",
            "Active Memory from PostgreSQL",
            memory_markdown(recalled_memories),
            source="postgres.memories.search",
            priority=75,
        ),
        make_section(
            "skill_index",
            "Available Skill Index",
            available_skill_index,
            source="postgres.skills.active_index",
            priority=58,
        ),
        make_section(
            "selected_skills",
            "Selected Skills",
            selected_skills,
            source="skill_runtime.selected",
            priority=74,
        ),
        make_section(
            "extracted_context",
            "Extracted Context",
            str(extracted_context or {}),
            source="graph.state.extracted_context",
            priority=55,
        ),
        make_section(
            "plan",
            "Current Plan",
            plan_markdown(plan or {}),
            source="graph.state.plan",
            priority=85,
        ),
        make_section(
            "critic_feedback",
            "Critic Feedback",
            critic_feedback_markdown(critic_directives or []),
            source="graph.state.critic_directives",
            priority=92,
        ),
        make_section(
            "team_summary",
            "Team Results",
            team_summary_markdown(store, session_id),
            source="store.agent_teams",
            priority=70,
        ),
        make_section(
            "subagent_summary",
            "Subagent Results",
            subagent_summary_markdown(store, session_id),
            source="store.subagent_runs",
            priority=70,
        ),
    ]


def make_section(
    name: str,
    title: str,
    content: str,
    *,
    source: str,
    priority: int,
) -> Section:
    normalized = str(content or "").strip()
    budget = SECTION_BUDGETS.get(name, 1200)
    return Section(
        name=name,
        title=title,
        content=normalized,
        source=source,
        priority=priority,
        render_order=RENDER_ORDER.get(name, 1000),
        budget_chars=budget,
        min_chars=min(SECTION_MIN_CHARS.get(name, 0), budget),
        required=name in REQUIRED_SECTIONS,
        original_chars=len(normalized),
    )


def subagent_summary_markdown(store: Any, session_id: str) -> str:
    if not session_id:
        return ""
    try:
        from ..subagents import subagent_summary_section
    except Exception as exc:  # noqa: BLE001
        logger.debug("Subagent summary section is unavailable: %s", exc)
        return ""
    try:
        return subagent_summary_section(store, parent_session_id=session_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unable to build subagent summary for session %s: %s", session_id, exc)
        return ""


def team_summary_markdown(store: Any, session_id: str) -> str:
    if not session_id:
        return ""
    try:
        from ..teams import team_summary_section
    except Exception as exc:  # noqa: BLE001
        logger.debug("Team summary section is unavailable: %s", exc)
        return ""
    try:
        return team_summary_section(store, parent_session_id=session_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unable to build team summary for session %s: %s", session_id, exc)
        return ""


def plan_markdown(plan: dict[str, Any]) -> str:
    steps = plan.get("steps") if isinstance(plan, dict) else None
    if not steps:
        return ""
    lines = []
    summary = str(plan.get("summary") or "").strip()
    if summary:
        lines.append(f"Goal: {summary}")
    for index, step in enumerate(steps, start=1):
        lines.append(f"{index}. {step}")
    return "\n".join(lines)


def critic_feedback_markdown(directives: list[dict[str, Any]]) -> str:
    lines = []
    for directive in directives[-4:]:
        kind = str(directive.get("kind") or "note").upper()
        message = str(directive.get("message") or "").strip()
        if message:
            lines.append(f"- [{kind}] {message}")
    return "\n".join(lines)


def memory_markdown(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return "No recalled memories."
    return "\n".join(f"- {item.get('content', '')}" for item in memories)


def read_optional(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()
