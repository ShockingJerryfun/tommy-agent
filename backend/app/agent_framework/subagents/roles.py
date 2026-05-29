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
from typing import Any

from ..agents import AgentDefinition, load_agent_registry
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
    description: str = ""
    permission_mode: str = "read_only"
    model: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


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


def _role_from_definition(definition: AgentDefinition) -> SubagentRole:
    return SubagentRole(
        id=definition.id,
        title=definition.title,
        description=definition.description,
        system_prompt=definition.system_prompt,
        tool_names=definition.tool_names,
        max_turns=definition.max_turns,
        max_wall_seconds=definition.max_wall_seconds,
        permission_mode=definition.permission_mode,
        model=definition.model,
        metadata=definition.metadata,
    )


def _roles() -> dict[str, SubagentRole]:
    registry = load_agent_registry(known_tool_names=set(_TOOLS_BY_NAME))
    return {
        definition_id: _role_from_definition(definition)
        for definition_id, definition in registry.as_dict().items()
    }


def role_registry() -> dict[str, SubagentRole]:
    """Read-only view of the registered roles."""

    return _roles()


def list_role_ids() -> list[str]:
    return list(_roles().keys())


def get_role(role_id: str) -> SubagentRole:
    roles = _roles()
    if role_id not in roles:
        raise KeyError(f"unknown subagent role: {role_id}")
    return roles[role_id]


def registry_for_role(role_id: str) -> ToolRegistry:
    """Build the bounded :class:`ToolRegistry` for a role."""

    role = get_role(role_id)
    tools: list[object] = []
    for name in role.tool_names:
        impl = _TOOLS_BY_NAME.get(name)
        if impl is not None:
            tools.append(impl)
    return _registry(*tools)
