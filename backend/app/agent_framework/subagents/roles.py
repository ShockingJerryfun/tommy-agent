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
from typing import TYPE_CHECKING, Any

from ..agents import AgentDefinition, AgentDefinitionResolver, AgentResolutionContext
from ..tool_runtime import ToolRegistry, create_default_registry

if TYPE_CHECKING:
    from ..workers.context import ChildRunContext


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


def _tools_by_name() -> dict[str, object]:
    return dict(create_default_registry().by_name)


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
    tools_by_name = _tools_by_name()
    resolver = AgentDefinitionResolver(known_tool_names=set(tools_by_name))
    return {
        role_id: _role_from_definition(
            resolver.resolve(role_id, AgentResolutionContext())
        )
        for role_id in (
            "researcher",
            "analyst",
            "writer",
            "architect",
            "reviewer",
            "tester",
            "explorer",
            "implementer",
        )
    }


def role_registry() -> dict[str, SubagentRole]:
    """Read-only view of the registered roles."""

    return _roles()


def list_role_ids() -> list[str]:
    return list(_roles().keys())


def get_role(role_id: str) -> SubagentRole:
    return resolve_role(role_id)


def resolve_role(
    role_id: str,
    *,
    child_context: ChildRunContext | None = None,
    agent_id: str = "default",
    workspace_dir: str = "",
) -> SubagentRole:
    """Resolve a subagent role against built-in, data, and workspace definitions."""

    effective_agent_id = child_context.parent_agent_id if child_context is not None else agent_id
    effective_workspace = (
        child_context.working_directory if child_context is not None else workspace_dir
    )
    resolver = AgentDefinitionResolver(known_tool_names=set(_tools_by_name()))
    definition = resolver.resolve(
        role_id,
        AgentResolutionContext(
            agent_id=effective_agent_id or "default",
            workspace_dir=effective_workspace or "",
        ),
    )
    return _role_from_definition(definition)


def registry_for_role(
    role_id: str,
    *,
    child_context: ChildRunContext | None = None,
    agent_id: str = "default",
    workspace_dir: str = "",
) -> ToolRegistry:
    """Build the bounded :class:`ToolRegistry` for a role."""

    role = resolve_role(
        role_id,
        child_context=child_context,
        agent_id=agent_id,
        workspace_dir=workspace_dir,
    )
    tools_by_name = _tools_by_name()
    tools: list[object] = []
    for name in role.tool_names:
        impl = tools_by_name.get(name)
        if impl is not None:
            tools.append(impl)
    return _registry(*tools)
