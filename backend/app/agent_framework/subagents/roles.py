"""Role-bound tool registries and permission overrides for subagents.

A subagent is *not* simply the parent agent on a different thread. It
gets a strictly smaller tool surface than the parent, baked into a
dedicated :class:`SubagentRole`. The role also carries a deny-bias
permission override: even if the parent's policy would allow a tool,
the subagent only executes tools whose names appear in the role
whitelist.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..tool_runtime import (
    ToolRegistry,
    get_current_time,
    list_local_directory,
    list_workspace,
    read_local_file,
    read_workspace_file,
    skill_propose,
    web_search,
    write_local_file,
)


@dataclass(frozen=True)
class SubagentRole:
    """Declarative spec for a subagent's persona and capabilities."""

    id: str
    title: str
    system_prompt: str
    tool_names: tuple[str, ...] = field(default_factory=tuple)
    max_turns: int = 6
    max_wall_seconds: float = 60.0


def _registry(*tools: object) -> ToolRegistry:
    return ToolRegistry(tools=tuple(tools))  # type: ignore[arg-type]


_TOOLS_BY_NAME = {
    "get_current_time": get_current_time,
    "web_search": web_search,
    "read_workspace_file": read_workspace_file,
    "list_workspace": list_workspace,
    "read_local_file": read_local_file,
    "list_local_directory": list_local_directory,
    "skill_propose": skill_propose,
    "write_local_file": write_local_file,
}


_ROLES: dict[str, SubagentRole] = {
    "researcher": SubagentRole(
        id="researcher",
        title="Researcher",
        system_prompt=(
            "You are a focused research subagent. Read sources carefully, "
            "cite URLs in markdown link form, and produce a tight, factual "
            "summary. You are read-only — never write files."
        ),
        tool_names=(
            "get_current_time",
            "web_search",
            "read_workspace_file",
            "list_workspace",
            "read_local_file",
            "list_local_directory",
        ),
        max_turns=6,
        max_wall_seconds=60.0,
    ),
    "analyst": SubagentRole(
        id="analyst",
        title="Analyst",
        system_prompt=(
            "You are an analyst subagent. Synthesize evidence into a clear "
            "argument with explicit claims, supporting facts, and citations. "
            "You are read-only."
        ),
        tool_names=(
            "get_current_time",
            "web_search",
            "read_workspace_file",
            "list_workspace",
            "read_local_file",
            "list_local_directory",
            "skill_propose",
        ),
        max_turns=8,
        max_wall_seconds=90.0,
    ),
    "writer": SubagentRole(
        id="writer",
        title="Writer",
        system_prompt=(
            "You are a writing subagent. Produce well-structured prose "
            "based on the supplied research. You may write a single output "
            "artifact via write_local_file. Cite external sources."
        ),
        tool_names=(
            "get_current_time",
            "read_workspace_file",
            "list_workspace",
            "read_local_file",
            "list_local_directory",
            "write_local_file",
        ),
        max_turns=6,
        max_wall_seconds=90.0,
    ),
}


def role_registry() -> dict[str, SubagentRole]:
    """Read-only view of the registered roles."""

    return dict(_ROLES)


def list_role_ids() -> list[str]:
    return list(_ROLES.keys())


def get_role(role_id: str) -> SubagentRole:
    if role_id not in _ROLES:
        raise KeyError(f"unknown subagent role: {role_id}")
    return _ROLES[role_id]


def registry_for_role(role_id: str) -> ToolRegistry:
    """Build the bounded :class:`ToolRegistry` for a role."""

    role = get_role(role_id)
    tools: list[object] = []
    for name in role.tool_names:
        impl = _TOOLS_BY_NAME.get(name)
        if impl is not None:
            tools.append(impl)
    return _registry(*tools)
