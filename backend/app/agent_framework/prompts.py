from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from langchain_core.messages import BaseMessage, SystemMessage

from .context import pact_markdown
from .skills import SkillCatalog
from .state import AgentState
from .store import SQLiteAgentStore

ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = ROOT / "data" / "agents"
_store = SQLiteAgentStore()


def _read_optional(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def render_system_prompt(state: AgentState) -> str:
    agent_id = state.get("agent_id", "default")
    agent_root = DATA_ROOT / agent_id
    extracted_context = state.get("extracted_context", {})
    metadata = state.get("metadata", {})
    frontend_settings = metadata.get("frontend_settings") if isinstance(metadata, dict) else {}
    working_directory = (
        str(frontend_settings.get("workingDirectory") or "").strip()
        if isinstance(frontend_settings, dict)
        else ""
    )
    session_id = state.get("session_id", "unknown")
    session = _store.get_session(str(session_id)) if session_id else None
    context_pact = _store.get_context_pact(str(session_id), agent_id=agent_id) if session_id else {}
    skills = SkillCatalog(agent_id=agent_id, store=_store).list_skills()
    last_user_message = ""
    for message in reversed(state.get("messages", [])):
        if getattr(message, "type", "") == "human":
            last_user_message = str(getattr(message, "content", ""))
            break
    recalled_memories = (
        _store.search_memories(agent_id=agent_id, query=last_user_message, limit=5)
        if last_user_message
        else []
    )

    sections = [
        "# Runtime",
        "You are running inside a LangGraph-first agent framework.",
        f"Current UTC time: {datetime.now(UTC).isoformat()}",
        f"Session ID: {session_id}",
        "# Session Summary",
        str((session or {}).get("summary") or "No summary yet."),
        "# SOUL",
        _read_optional(agent_root / "SOUL.md"),
        "# USER",
        _read_optional(agent_root / "USER.md"),
        "# MEMORY",
        _read_optional(agent_root / "MEMORY.md"),
        "# Active Memory Recall",
        "\n".join(f"- {item['content']}" for item in recalled_memories) or "No recalled memories.",
        "# Context Pact",
        pact_markdown(context_pact),
        "# Installed Skills",
        "\n".join(f"- {skill.name}: {skill.description or skill.path}" for skill in skills)
        or "No installed skills.",
        "# Extracted Context",
        str(extracted_context or {}),
        "# Session Metadata",
        str(metadata or {}),
        "# Working Directory",
        working_directory
        or (
            "No working directory selected. "
            "Use the configured workspace root when tools need files."
        ),
        "# Tool Use",
        (
            "Use tools when they materially improve the answer. If a tool fails, "
            "inspect the error and retry with corrected arguments when appropriate."
        ),
        (
            "Use web_search for current external facts, documentation, news, prices, "
            "or claims that need citation. Prefer small max_results, fast search_depth, "
            "no raw content, and targeted domains/time ranges to save context."
        ),
        (
            "When a working directory is selected, treat it as the default project scope "
            "for conversation context, file tools, and shell commands. Do not read, write, "
            "or run commands outside it unless the user explicitly changes the working directory."
        ),
        (
            "Local file tools may read, list, and write files under the active working directory "
            "or configured local file access root. Use exact paths and avoid unnecessary edits."
        ),
        "# Memory Boundary",
        (
            "Do not claim you have permanently remembered something unless the runtime reports "
            "a confirmed memory write. If the user asks you to remember something, acknowledge "
            "that it has been proposed for confirmation."
        ),
    ]
    return "\n\n".join(section for section in sections if section)


def messages_with_system_prompt(state: AgentState) -> list[BaseMessage]:
    return [SystemMessage(content=render_system_prompt(state)), *state.get("messages", [])]
