"""AgentDefinitionResolver precedence and validation tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent_framework.agents import AgentDefinitionResolver, AgentResolutionContext

KNOWN_TOOLS = {
    "get_current_time",
    "list_workspace",
    "list_local_directory",
    "read_workspace_file",
    "read_local_file",
    "skill_propose",
    "web_search",
    "write_local_file",
}


def _write_agent(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_resolver_uses_builtin_fallback() -> None:
    definition = AgentDefinitionResolver(known_tool_names=KNOWN_TOOLS).resolve(
        "reviewer",
        AgentResolutionContext(),
    )

    assert definition.id == "reviewer"
    assert definition.title == "Reviewer"


def test_resolver_uses_data_directory_override(tmp_path: Path) -> None:
    _write_agent(
        tmp_path / "agent-a" / "agents" / "reviewer.md",
        """---
id: reviewer
title: Data Reviewer
tools:
  - read_workspace_file
---
Use data-root instructions.
""",
    )

    definition = AgentDefinitionResolver(data_root=tmp_path, known_tool_names=KNOWN_TOOLS).resolve(
        "reviewer",
        AgentResolutionContext(agent_id="agent-a"),
    )

    assert definition.title == "Data Reviewer"
    assert definition.system_prompt == "Use data-root instructions."


def test_resolver_workspace_override_wins_over_data_and_builtin(tmp_path: Path) -> None:
    _write_agent(
        tmp_path / "data" / "agent-a" / "agents" / "reviewer.md",
        """---
id: reviewer
title: Data Reviewer
tools:
  - read_workspace_file
---
Use data-root instructions.
""",
    )
    _write_agent(
        tmp_path / "workspace" / ".tommy" / "agents" / "reviewer.md",
        """---
id: reviewer
title: Workspace Reviewer
tools:
  - list_workspace
---
Use workspace instructions.
""",
    )

    definition = AgentDefinitionResolver(
        data_root=tmp_path / "data",
        known_tool_names=KNOWN_TOOLS,
    ).resolve(
        "reviewer",
        AgentResolutionContext(agent_id="agent-a", workspace_dir=str(tmp_path / "workspace")),
    )

    assert definition.title == "Workspace Reviewer"
    assert definition.system_prompt == "Use workspace instructions."
    assert definition.tool_names == ("list_workspace",)


def test_resolver_unknown_role_raises_key_error() -> None:
    resolver = AgentDefinitionResolver(known_tool_names=KNOWN_TOOLS)

    with pytest.raises(KeyError):
        resolver.resolve("missing-role", AgentResolutionContext())


def test_resolver_unknown_tool_raises_value_error(tmp_path: Path) -> None:
    _write_agent(
        tmp_path / ".tommy" / "agents" / "reviewer.md",
        """---
id: reviewer
title: Reviewer
tools:
  - unknown_tool
---
Use unsafe instructions.
""",
    )

    resolver = AgentDefinitionResolver(known_tool_names=KNOWN_TOOLS)

    with pytest.raises(ValueError, match="unknown tool"):
        resolver.resolve("reviewer", AgentResolutionContext(workspace_dir=str(tmp_path)))


def test_resolver_removes_disallowed_tools(tmp_path: Path) -> None:
    _write_agent(
        tmp_path / ".tommy" / "agents" / "writer.md",
        """---
id: writer
title: Safe Writer
tools:
  - read_workspace_file
  - write_local_file
disallowed_tools:
  - write_local_file
---
Read only.
""",
    )

    definition = AgentDefinitionResolver(known_tool_names=KNOWN_TOOLS).resolve(
        "writer",
        AgentResolutionContext(workspace_dir=str(tmp_path)),
    )

    assert definition.tool_names == ("read_workspace_file",)
    assert definition.disallowed_tool_names == ("write_local_file",)
