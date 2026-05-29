"""AgentDefinition registry with validation and override semantics."""

from __future__ import annotations

from collections.abc import Iterable

from .definitions import AgentDefinition


class AgentRegistry:
    """Validated mapping of agent definition id to definition."""

    def __init__(
        self,
        definitions: Iterable[AgentDefinition],
        *,
        known_tool_names: set[str] | None = None,
    ) -> None:
        self._definitions: dict[str, AgentDefinition] = {}
        for definition in definitions:
            validated = self._validate(definition, known_tool_names).with_tool_policy_applied()
            self._definitions[validated.id] = validated

    def get(self, definition_id: str) -> AgentDefinition:
        try:
            return self._definitions[definition_id]
        except KeyError as exc:
            raise KeyError(f"unknown agent definition: {definition_id}") from exc

    def ids(self) -> list[str]:
        return list(self._definitions.keys())

    def as_dict(self) -> dict[str, AgentDefinition]:
        return dict(self._definitions)

    @staticmethod
    def _validate(
        definition: AgentDefinition,
        known_tool_names: set[str] | None,
    ) -> AgentDefinition:
        if not definition.id or not definition.title or not definition.system_prompt:
            raise ValueError("agent definition id, title, and system_prompt are required")
        if known_tool_names is None:
            return definition
        for name in definition.tool_names + definition.disallowed_tool_names:
            if name not in known_tool_names:
                raise ValueError(
                    f"agent definition {definition.id!r} references unknown tool {name!r}"
                )
        return definition
