"""Externalizable agent definitions and registries."""

from __future__ import annotations

from .definitions import AgentDefinition, built_in_agent_definitions
from .loader import load_agent_definitions, load_agent_registry
from .registry import AgentRegistry
from .resolver import AgentDefinitionResolver, AgentResolutionContext

__all__ = [
    "AgentDefinition",
    "AgentDefinitionResolver",
    "AgentResolutionContext",
    "AgentRegistry",
    "built_in_agent_definitions",
    "load_agent_definitions",
    "load_agent_registry",
]
