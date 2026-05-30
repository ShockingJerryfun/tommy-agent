"""ChildRunService chokepoint tests."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from app.agent_framework.storage import PostgresAgentStore
from app.agent_framework.subagents import SubagentRole
from app.agent_framework.tool_runtime import ToolRegistry
from app.agent_framework.workers.child_run_service import ChildRunRequest, ChildRunService
from app.agent_framework.workers.context import derive_child_context


def _store() -> PostgresAgentStore:
    store = PostgresAgentStore()
    store.reset_for_tests()
    return store


def _new_session(store: PostgresAgentStore) -> tuple[str, str]:
    session_id = f"sess-{uuid.uuid4().hex[:10]}"
    store.create_session(session_id=session_id, agent_id="default", title="t")
    run_id = f"run-{uuid.uuid4().hex[:10]}"
    return session_id, run_id


def _write_agent(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_child_run_service_creates_child_result_with_fake_runner() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)

    def runner(
        prompt: str,
        registry: ToolRegistry,
        role: SubagentRole,
        thread_config: dict[str, Any],
    ) -> dict[str, Any]:
        assert role.id == "researcher"
        assert thread_config["configurable"]["thread_id"]
        assert "Task:\nresearch x" in prompt
        return {"final_response": "Found https://example.com", "status": "completed"}

    context = derive_child_context(
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        role_id="researcher",
    )
    result = ChildRunService(store, runner=runner).run(
        ChildRunRequest(task="research x", role_id="researcher", context=context)
    )

    assert result.status == "completed"
    assert result.role_id == "researcher"
    assert result.score > 0.0
    assert result.child_session_id
    rows = store.subagent_runs.list_for_session(parent_session_id)
    assert rows[0]["id"] == result.subagent_id
    assert rows[0]["status"] == "completed"


def test_child_run_service_uses_workspace_role_override_in_prompt(tmp_path: Path) -> None:
    _write_agent(
        tmp_path / ".tommy" / "agents" / "reviewer.md",
        """---
id: reviewer
title: Workspace Reviewer
tools:
  - read_workspace_file
---
WORKSPACE REVIEWER PROMPT.
""",
    )
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)
    seen: dict[str, Any] = {}

    def runner(
        prompt: str,
        registry: ToolRegistry,
        role: SubagentRole,
        thread_config: dict[str, Any],
    ) -> dict[str, Any]:
        seen["prompt"] = prompt
        seen["role_title"] = role.title
        seen["tool_names"] = {tool.name for tool in registry.tools}
        return {"final_response": "reviewed", "status": "completed"}

    context = derive_child_context(
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        parent_metadata={"frontend_settings": {"workingDirectory": str(tmp_path)}},
        role_id="reviewer",
    )

    ChildRunService(store, runner=runner).run(
        ChildRunRequest(task="review code", role_id="reviewer", context=context)
    )

    assert "WORKSPACE REVIEWER PROMPT." in seen["prompt"]
    assert seen["role_title"] == "Workspace Reviewer"
    assert seen["tool_names"] == {"read_workspace_file"}


def test_child_run_service_blocks_team_and_workflow_tools_for_child_runs(
    tmp_path: Path,
) -> None:
    _write_agent(
        tmp_path / ".tommy" / "agents" / "reviewer.md",
        """---
id: reviewer
title: Workspace Reviewer
tools:
  - read_workspace_file
  - create_agent_team
  - run_agent_workflow
---
Try to spawn more work.
""",
    )
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)
    seen_tool_names: set[str] = set()

    def runner(
        prompt: str,
        registry: ToolRegistry,
        role: SubagentRole,
        thread_config: dict[str, Any],
    ) -> dict[str, Any]:
        seen_tool_names.update(tool.name for tool in registry.tools)
        return {"final_response": "safe", "status": "completed"}

    context = derive_child_context(
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        parent_metadata={"frontend_settings": {"workingDirectory": str(tmp_path)}},
        role_id="reviewer",
    )

    ChildRunService(store, runner=runner).run(
        ChildRunRequest(task="review code", role_id="reviewer", context=context)
    )

    assert "read_workspace_file" in seen_tool_names
    assert "create_agent_team" not in seen_tool_names
    assert "run_agent_workflow" not in seen_tool_names


def test_child_run_service_persists_lineage_metadata() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)

    def runner(*_: Any, **__: Any) -> dict[str, Any]:
        return {"final_response": "ok", "status": "completed"}

    context = derive_child_context(
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        parent_agent_id="agent-1",
        parent_metadata={
            "team_id": "team-1",
            "team_task_id": "task-1",
            "workflow_run_id": "workflow-1",
            "phase_run_id": "phase-run-1",
            "workflow_phase_id": "phase-1",
            "approval_id": "approval-1",
            "frontend_settings": {
                "workingDirectory": "/repo",
                "commandScope": "restricted",
            },
            "permission_mode": "read_only",
            "model": "deepseek-chat",
            "budget": {"max_turns": 2},
        },
        role_id="tester",
    )

    ChildRunService(store, runner=runner).run(
        ChildRunRequest(task="test", role_id="tester", context=context)
    )

    metadata = store.subagent_runs.list_for_session(parent_session_id)[0]["metadata"]
    assert metadata["parent_session_id"] == parent_session_id
    assert metadata["parent_run_id"] == parent_run_id
    assert metadata["parent_agent_id"] == "agent-1"
    assert metadata["subagent_role"] == "tester"
    assert metadata["team_id"] == "team-1"
    assert metadata["team_task_id"] == "task-1"
    assert metadata["workflow_run_id"] == "workflow-1"
    assert metadata["phase_run_id"] == "phase-run-1"
    assert metadata["workflow_phase_id"] == "phase-1"
    assert metadata["approval_id"] == "approval-1"
    assert metadata["working_directory"] == "/repo"
    assert metadata["command_scope"] == "restricted"
    assert metadata["permission_mode"] == "read_only"
    assert metadata["model"] == "deepseek-chat"
    assert metadata["budget"] == {"max_turns": 2}
    assert metadata["depth"] == 1


def test_child_run_service_stores_runner_failure_as_failed_result() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)

    def runner(*_: Any, **__: Any) -> dict[str, Any]:
        raise RuntimeError("model exploded")

    context = derive_child_context(
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        role_id="analyst",
    )
    result = ChildRunService(store, runner=runner).run(
        ChildRunRequest(task="analyze", role_id="analyst", context=context)
    )

    assert result.status == "failed"
    assert "model exploded" in result.final_response
    row = store.subagent_runs.list_for_session(parent_session_id)[0]
    assert row["status"] == "failed"
    assert "model exploded" in row["final_response"]


def test_child_run_service_short_circuits_when_parent_run_is_stopped() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)
    store.create_run(
        session_id=parent_session_id,
        agent_id="default",
        input="hi",
        run_id=parent_run_id,
        status="running",
    )
    store.runs.request_run_cancel(parent_run_id)
    called = False

    def runner(*_: Any, **__: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return {"final_response": "should not run", "status": "completed"}

    context = derive_child_context(
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        role_id="researcher",
    )
    result = ChildRunService(store, runner=runner).run(
        ChildRunRequest(task="research", role_id="researcher", context=context)
    )

    assert called is False
    assert result.status == "stopped"
    assert store.subagent_runs.list_for_session(parent_session_id) == []
