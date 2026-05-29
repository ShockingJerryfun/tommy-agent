"""AgentDefinition registry tests for externalizable subagent roles."""

from __future__ import annotations

from pathlib import Path

from app.agent_framework.agents import load_agent_registry
from app.agent_framework.subagents import list_role_ids, registry_for_role, role_registry


def _write_agent(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_builtin_agent_definitions_include_existing_and_future_roles() -> None:
    ids = set(list_role_ids())

    assert {"researcher", "analyst", "writer"}.issubset(ids)
    assert {"architect", "reviewer", "tester", "explorer", "implementer"}.issubset(ids)


def test_role_registry_is_derived_from_agent_definitions() -> None:
    roles = role_registry()

    assert roles["researcher"].title == "Researcher"
    assert roles["researcher"].system_prompt
    assert registry_for_role("researcher").by_name


def test_markdown_frontmatter_definition_loads_from_workspace(tmp_path: Path) -> None:
    _write_agent(
        tmp_path / ".tommy" / "agents" / "reviewer.md",
        """---
id: reviewer
title: Reviewer
description: Reviews code for correctness and regressions.
tools:
  - list_workspace
  - read_workspace_file
disallowed_tools:
  - write_local_file
max_turns: 8
max_wall_seconds: 180
permission_mode: read_only
---
You are a strict reviewer.
""",
    )

    registry = load_agent_registry(workspace_dir=tmp_path)
    definition = registry.get("reviewer")

    assert definition.id == "reviewer"
    assert definition.title == "Reviewer"
    assert definition.description == "Reviews code for correctness and regressions."
    assert definition.tool_names == ("list_workspace", "read_workspace_file")
    assert definition.disallowed_tool_names == ("write_local_file",)
    assert definition.max_turns == 8
    assert definition.max_wall_seconds == 180.0
    assert definition.permission_mode == "read_only"
    assert definition.system_prompt == "You are a strict reviewer."


def test_workspace_definition_overrides_builtin_definition(tmp_path: Path) -> None:
    _write_agent(
        tmp_path / ".tommy" / "agents" / "researcher.md",
        """---
id: researcher
title: Workspace Researcher
tools:
  - read_workspace_file
max_turns: 3
---
Use only workspace evidence.
""",
    )

    registry = load_agent_registry(workspace_dir=tmp_path)
    definition = registry.get("researcher")

    assert definition.title == "Workspace Researcher"
    assert definition.system_prompt == "Use only workspace evidence."
    assert definition.tool_names == ("read_workspace_file",)
    assert definition.max_turns == 3


def test_disallowed_tools_are_removed_from_final_definition(tmp_path: Path) -> None:
    _write_agent(
        tmp_path / ".tommy" / "agents" / "implementer.md",
        """---
id: implementer
title: Safe Implementer
tools:
  - read_workspace_file
  - write_local_file
disallowed_tools:
  - write_local_file
---
Read the code and propose a patch.
""",
    )

    registry = load_agent_registry(workspace_dir=tmp_path)
    definition = registry.get("implementer")

    assert definition.tool_names == ("read_workspace_file",)
    assert "write_local_file" not in definition.tool_names
