"""AgentDefinition models and built-in subagent personas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_MAX_TURNS = 6
DEFAULT_MAX_WALL_SECONDS = 60.0
DEFAULT_PERMISSION_MODE = "read_only"


@dataclass(frozen=True)
class AgentDefinition:
    """Declarative definition for a bounded child agent."""

    id: str
    title: str
    description: str
    system_prompt: str
    tool_names: tuple[str, ...] = field(default_factory=tuple)
    disallowed_tool_names: tuple[str, ...] = field(default_factory=tuple)
    max_turns: int = DEFAULT_MAX_TURNS
    max_wall_seconds: float = DEFAULT_MAX_WALL_SECONDS
    model: str | None = None
    permission_mode: str = DEFAULT_PERMISSION_MODE
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", str(self.id).strip())
        object.__setattr__(self, "title", str(self.title).strip())
        object.__setattr__(self, "description", str(self.description or "").strip())
        object.__setattr__(self, "system_prompt", str(self.system_prompt).strip())
        object.__setattr__(self, "tool_names", _clean_names(self.tool_names))
        object.__setattr__(self, "disallowed_tool_names", _clean_names(self.disallowed_tool_names))
        object.__setattr__(self, "max_turns", max(1, int(self.max_turns or DEFAULT_MAX_TURNS)))
        wall_seconds = float(self.max_wall_seconds or DEFAULT_MAX_WALL_SECONDS)
        object.__setattr__(self, "max_wall_seconds", max(1.0, wall_seconds))
        model = str(self.model).strip() if self.model else None
        object.__setattr__(self, "model", model or None)
        mode = (
            str(self.permission_mode or DEFAULT_PERMISSION_MODE).strip()
            or DEFAULT_PERMISSION_MODE
        )
        object.__setattr__(self, "permission_mode", mode)
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

        if not self.id:
            raise ValueError("agent definition id must be non-empty")
        if not self.title:
            raise ValueError(f"agent definition {self.id!r} title must be non-empty")
        if not self.system_prompt:
            raise ValueError(f"agent definition {self.id!r} system_prompt must be non-empty")

    def with_tool_policy_applied(self) -> AgentDefinition:
        disallowed = set(self.disallowed_tool_names)
        allowed = tuple(name for name in self.tool_names if name not in disallowed)
        return AgentDefinition(
            id=self.id,
            title=self.title,
            description=self.description,
            system_prompt=self.system_prompt,
            tool_names=allowed,
            disallowed_tool_names=self.disallowed_tool_names,
            max_turns=self.max_turns,
            max_wall_seconds=self.max_wall_seconds,
            model=self.model,
            permission_mode=self.permission_mode,
            metadata=self.metadata,
        )


def _clean_names(values: tuple[str, ...] | list[str] | str | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        raw_values = [values]
    else:
        raw_values = list(values)
    names: list[str] = []
    for value in raw_values:
        name = str(value).strip()
        if not name:
            raise ValueError("tool names must be non-empty")
        if name not in names:
            names.append(name)
    return tuple(names)


def built_in_agent_definitions() -> tuple[AgentDefinition, ...]:
    """Return built-in definitions that work without workspace files."""

    read_tools = (
        "get_current_time",
        "web_search",
        "read_workspace_file",
        "list_workspace",
        "read_local_file",
        "list_local_directory",
    )
    workspace_read_tools = (
        "get_current_time",
        "read_workspace_file",
        "list_workspace",
        "read_local_file",
        "list_local_directory",
    )
    return (
        AgentDefinition(
            id="researcher",
            title="Researcher",
            description="Finds and summarizes factual evidence from web and workspace sources.",
            system_prompt=(
                "You are a focused research subagent. Read sources carefully, "
                "cite URLs in markdown link form, and produce a tight, factual "
                "summary. You are read-only - never write files."
            ),
            tool_names=read_tools,
            max_turns=6,
            max_wall_seconds=60.0,
        ),
        AgentDefinition(
            id="analyst",
            title="Analyst",
            description="Synthesizes evidence into explicit claims and supporting facts.",
            system_prompt=(
                "You are an analyst subagent. Synthesize evidence into a clear "
                "argument with explicit claims, supporting facts, and citations. "
                "You are read-only."
            ),
            tool_names=read_tools + ("skill_propose",),
            max_turns=8,
            max_wall_seconds=90.0,
        ),
        AgentDefinition(
            id="writer",
            title="Writer",
            description="Writes a bounded artifact from supplied research.",
            system_prompt=(
                "You are a writing subagent. Produce well-structured prose "
                "based on the supplied research. You may write a single output "
                "artifact via write_local_file. Cite external sources."
            ),
            tool_names=workspace_read_tools + ("write_local_file",),
            max_turns=6,
            max_wall_seconds=90.0,
            permission_mode="workspace_write",
        ),
        AgentDefinition(
            id="architect",
            title="Architect",
            description="Plans implementation structure and integration boundaries.",
            system_prompt=(
                "You are an architecture subagent. Produce concise implementation "
                "plans, identify interfaces, and call out migration or compatibility "
                "risks. You are read-only."
            ),
            tool_names=workspace_read_tools,
            max_turns=8,
            max_wall_seconds=120.0,
        ),
        AgentDefinition(
            id="reviewer",
            title="Reviewer",
            description="Reviews code for correctness, regressions, and missing tests.",
            system_prompt=(
                "You are a strict reviewer subagent. Focus on concrete bugs, "
                "behavioral regressions, unsafe assumptions, and missing tests. "
                "You are read-only."
            ),
            tool_names=workspace_read_tools,
            max_turns=8,
            max_wall_seconds=120.0,
        ),
        AgentDefinition(
            id="tester",
            title="Tester",
            description="Designs and evaluates focused test coverage.",
            system_prompt=(
                "You are a testing subagent. Identify meaningful test cases, edge "
                "conditions, and verification commands. You are read-only."
            ),
            tool_names=workspace_read_tools,
            max_turns=8,
            max_wall_seconds=120.0,
        ),
        AgentDefinition(
            id="explorer",
            title="Explorer",
            description="Inspects repositories and reports relevant structure and risks.",
            system_prompt=(
                "You are an exploration subagent. Inspect the workspace, map the "
                "relevant files and contracts, and return a compact evidence-backed "
                "summary. You are read-only."
            ),
            tool_names=workspace_read_tools,
            max_turns=8,
            max_wall_seconds=120.0,
        ),
        AgentDefinition(
            id="implementer",
            title="Implementer",
            description="Proposes implementation changes without applying them by default.",
            system_prompt=(
                "You are an implementation subagent. Read the code and propose a "
                "small, compatible implementation plan or patch outline. Do not "
                "write files unless explicitly granted a write-capable tool scope."
            ),
            tool_names=workspace_read_tools,
            disallowed_tool_names=("write_local_file",),
            max_turns=8,
            max_wall_seconds=120.0,
        ),
    )
