"""Context-aware AgentDefinition resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..tool_runtime import create_default_registry
from .definitions import AgentDefinition
from .loader import load_agent_definitions
from .registry import AgentRegistry

_FUTURE_SPAWN_TOOL_NAMES = {
    "create_agent_team",
    "run_agent_team",
    "get_agent_team_status",
    "create_agent_workflow",
    "run_agent_workflow",
    "get_agent_workflow_status",
}


@dataclass(frozen=True)
class AgentResolutionContext:
    agent_id: str = "default"
    workspace_dir: str = ""


class AgentDefinitionResolver:
    """Resolve validated definitions with workspace overrides taking precedence."""

    def __init__(
        self,
        *,
        data_root: str | Path | None = None,
        known_tool_names: set[str] | None = None,
    ) -> None:
        self._data_root = data_root
        self._known_tool_names = (
            set(known_tool_names) if known_tool_names is not None else _default_tool_names()
        )

    def resolve(self, role_id: str, context: AgentResolutionContext) -> AgentDefinition:
        definitions = load_agent_definitions(
            agent_id=context.agent_id,
            workspace_dir=context.workspace_dir or None,
            data_root=self._data_root,
        )
        registry = AgentRegistry(definitions, known_tool_names=self._known_tool_names)
        return registry.get(role_id)


def _default_tool_names() -> set[str]:
    return {tool.name for tool in create_default_registry().tools} | _FUTURE_SPAWN_TOOL_NAMES
