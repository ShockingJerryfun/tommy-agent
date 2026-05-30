"""Tool integration tests for the multi-agent runtime."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from app.agent_framework.storage import PostgresAgentStore
from app.agent_framework.subagents import SubagentRole, registry_for_role
from app.agent_framework.tool_runtime import ToolRegistry, create_default_registry
from app.agent_framework.tool_runtime.approvals import evaluate_tool_call


def _store() -> PostgresAgentStore:
    store = PostgresAgentStore()
    store.reset_for_tests()
    return store


def _new_session(store: PostgresAgentStore) -> tuple[str, str]:
    session_id = f"sess-{uuid.uuid4().hex[:10]}"
    store.create_session(session_id=session_id, agent_id="default", title="t")
    run_id = f"run-{uuid.uuid4().hex[:10]}"
    store.create_run(
        session_id=session_id,
        agent_id="default",
        input="tool",
        run_id=run_id,
        status="running",
    )
    return session_id, run_id


def _write_agent(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_default_registry_exposes_multi_agent_tools_but_subagents_do_not() -> None:
    default_names = set(create_default_registry().by_name)
    researcher_names = set(registry_for_role("researcher").by_name)

    assert {"create_agent_team", "run_agent_workflow"}.issubset(default_names)
    assert "create_agent_team" not in researcher_names
    assert "run_agent_workflow" not in researcher_names


def test_multi_agent_tools_require_approval() -> None:
    team_decision = evaluate_tool_call(
        "create_agent_team",
        {"goal": "audit", "members": [{"role": "reviewer"}]},
    )
    workflow_decision = evaluate_tool_call(
        "run_agent_workflow",
        {"workflow_yaml": "id: x\nname: X\nphases: []"},
    )

    assert team_decision.needs_approval is True
    assert workflow_decision.needs_approval is True
    assert team_decision.risk_level == "medium"
    assert workflow_decision.risk_level == "medium"


def test_multi_agent_tools_require_approval_even_in_unrestricted_scope() -> None:
    team_decision = evaluate_tool_call(
        "create_agent_team",
        {"goal": "audit", "members": [{"role": "reviewer"}]},
        command_scope="unrestricted",
    )
    workflow_decision = evaluate_tool_call(
        "run_agent_workflow",
        {"workflow_yaml": "id: x\nname: X\nphases: []"},
        command_scope="unrestricted",
    )

    assert team_decision.needs_approval is True
    assert workflow_decision.needs_approval is True


def test_create_agent_team_tool_queues_without_approval() -> None:
    payload = json.loads(
        create_default_registry().invoke(
            "create_agent_team",
            {
                "goal": "Audit storage",
                "members": [{"role": "reviewer", "agent_definition_id": "reviewer"}],
                "tasks": [{"title": "Review repos", "description": "Check persistence"}],
            },
            context={"session_id": "sess-test", "run_id": "run-test"},
        )
    )

    assert payload["status"] == "queued"
    assert payload["team_id"] == ""
    assert payload["summary"]


def test_create_agent_team_tool_creates_team_when_approved() -> None:
    store = _store()
    session_id, run_id = _new_session(store)
    payload = json.loads(
        create_default_registry().invoke(
            "create_agent_team",
            {
                "goal": "Audit storage",
                "members": [{"role": "reviewer", "agent_definition_id": "reviewer"}],
                "tasks": [{"title": "Review repos", "description": "Check persistence"}],
            },
            context={
                "session_id": session_id,
                "run_id": run_id,
                "approval_granted": True,
                "approval_id": "appr-test",
                "frontend_settings": {
                    "workingDirectory": "/repo",
                    "commandScope": "restricted",
                },
                "metadata": {
                    "run_id": run_id,
                    "frontend_settings": {
                        "workingDirectory": "/repo",
                        "commandScope": "restricted",
                    },
                    "permission_mode": "read_only",
                },
            },
        )
    )

    assert payload["status"] == "queued"
    assert payload["team_id"].startswith("team-")
    assert payload["task_count"] == 1
    assert store.agent_teams.get(payload["team_id"]) is not None
    team = store.agent_teams.get(payload["team_id"])
    assert team is not None
    assert team["metadata"]["approval_id"] == "appr-test"
    assert team["metadata"]["working_directory"] == "/repo"
    assert team["metadata"]["command_scope"] == "restricted"
    assert team["metadata"]["permission_mode"] == "read_only"


def test_delegate_task_tool_forwards_parent_metadata_to_run_delegate_task(
    tmp_path: Path,
    monkeypatch,
) -> None:
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
    session_id, run_id = _new_session(store)
    seen: dict[str, Any] = {}

    def runner(
        prompt: str,
        registry: ToolRegistry,
        role: SubagentRole,
        thread_config: dict[str, Any],
    ) -> dict[str, Any]:
        seen["prompt"] = prompt
        seen["role"] = role.title
        return {"final_response": "reviewed", "status": "completed"}

    monkeypatch.setattr(
        "app.agent_framework.subagents.orchestrator.get_agent_store",
        lambda: store,
    )
    monkeypatch.setattr(
        "app.agent_framework.workers.child_run_service.default_subagent_runner",
        runner,
    )

    payload = json.loads(
        create_default_registry().invoke(
            "delegate_task",
            {"task": "review", "target_agent": "reviewer", "reason": "test"},
            context={
                "session_id": session_id,
                "run_id": run_id,
                "agent_id": "default",
                "approval_granted": True,
                "approval_id": "appr-delegate",
                "frontend_settings": {"workingDirectory": str(tmp_path)},
                "metadata": {
                    "run_id": run_id,
                    "frontend_settings": {"workingDirectory": str(tmp_path)},
                },
            },
        )
    )

    assert payload["status"] == "completed"
    assert seen["role"] == "Workspace Reviewer"
    assert "WORKSPACE REVIEWER PROMPT." in seen["prompt"]


def test_run_agent_workflow_tool_queues_without_approval() -> None:
    payload = json.loads(
        create_default_registry().invoke(
            "run_agent_workflow",
            {
                "workflow_yaml": """
id: audit
name: Audit
phases:
  - id: inspect
    kind: single
    agent: explorer
    prompt: Inspect repository
""",
            },
            context={"session_id": "sess-test", "run_id": "run-test"},
        )
    )

    assert payload["status"] == "queued"
    assert payload["workflow_run_id"] == ""
    assert payload["summary"]
