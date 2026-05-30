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

    assert {
        "create_agent_team",
        "run_agent_team",
        "get_agent_team_status",
        "cancel_agent_team_run",
        "run_agent_workflow",
        "get_agent_workflow_status",
        "cancel_agent_workflow_run",
        "rerun_failed_workflow_phase",
    }.issubset(default_names)
    assert "create_agent_team" not in researcher_names
    assert "run_agent_team" not in researcher_names
    assert "get_agent_team_status" not in researcher_names
    assert "cancel_agent_team_run" not in researcher_names
    assert "run_agent_workflow" not in researcher_names
    assert "get_agent_workflow_status" not in researcher_names
    assert "cancel_agent_workflow_run" not in researcher_names
    assert "rerun_failed_workflow_phase" not in researcher_names


def test_multi_agent_tools_require_approval() -> None:
    team_decision = evaluate_tool_call(
        "run_agent_team",
        {"team_id": "team-1"},
    )
    workflow_decision = evaluate_tool_call(
        "run_agent_workflow",
        {"workflow_yaml": "id: x\nname: X\nphases: []"},
    )
    status_decision = evaluate_tool_call(
        "get_agent_team_status",
        {"team_run_id": "team-run-1"},
    )
    cancel_decision = evaluate_tool_call(
        "cancel_agent_workflow_run",
        {"workflow_run_id": "workflow-1"},
    )

    assert team_decision.needs_approval is True
    assert workflow_decision.needs_approval is True
    assert status_decision.needs_approval is False
    assert cancel_decision.needs_approval is True
    assert team_decision.risk_level == "medium"
    assert workflow_decision.risk_level == "medium"


def test_multi_agent_tools_require_approval_even_in_unrestricted_scope() -> None:
    team_decision = evaluate_tool_call(
        "run_agent_team",
        {"team_id": "team-1"},
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


def test_run_agent_team_tool_enqueues_and_status_can_be_polled(monkeypatch) -> None:
    store = _store()
    session_id, run_id = _new_session(store)
    registry = create_default_registry()
    enqueued: list[tuple[str, str]] = []

    class FakeQueue:
        def enqueue(self, run_id: str, kind: str, coroutine_factory, metadata=None):
            enqueued.append((run_id, kind))
            return {"run_id": run_id, "kind": kind}

    import app.agent_framework.tool_modules.collaboration as collaboration

    monkeypatch.setattr(collaboration, "_BACKGROUND_QUEUE", FakeQueue(), raising=False)
    created = json.loads(
        registry.invoke(
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
                "approval_id": "appr-create",
            },
        )
    )

    queued = json.loads(
        registry.invoke(
            "run_agent_team",
            {"team_id": created["team_id"]},
            context={
                "session_id": session_id,
                "run_id": run_id,
                "approval_granted": False,
            },
        )
    )
    assert queued["status"] == "queued"
    assert queued["team_run_id"] == ""

    running = json.loads(
        registry.invoke(
            "run_agent_team",
            {"team_id": created["team_id"]},
            context={
                "session_id": session_id,
                "run_id": run_id,
                "approval_granted": True,
                "approval_id": "appr-run",
            },
        )
    )

    assert running["status"] in {"queued", "running"}
    assert running["team_run_id"].startswith("team-run-")
    assert enqueued == [(running["team_run_id"], "team")]
    status = json.loads(
        registry.invoke(
            "get_agent_team_status",
            {"team_run_id": running["team_run_id"]},
            context={"session_id": session_id, "run_id": run_id},
        )
    )
    assert status["team_run_id"] == running["team_run_id"]
    assert "tasks" in status


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


def test_run_agent_workflow_tool_enqueues_when_approved_and_status_can_be_polled(
    monkeypatch,
) -> None:
    store = _store()
    session_id, run_id = _new_session(store)
    registry = create_default_registry()
    enqueued: list[tuple[str, str]] = []

    class FakeQueue:
        def enqueue(self, run_id: str, kind: str, coroutine_factory, metadata=None):
            enqueued.append((run_id, kind))
            return {"run_id": run_id, "kind": kind}

    import app.agent_framework.tool_modules.collaboration as collaboration

    monkeypatch.setattr(collaboration, "_BACKGROUND_QUEUE", FakeQueue(), raising=False)

    payload = json.loads(
        registry.invoke(
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
            context={
                "session_id": session_id,
                "run_id": run_id,
                "approval_granted": True,
                "approval_id": "appr-workflow",
            },
        )
    )

    assert payload["status"] in {"queued", "running"}
    assert payload["workflow_run_id"].startswith("workflow-")
    assert enqueued == [(payload["workflow_run_id"], "workflow")]
    status = json.loads(
        registry.invoke(
            "get_agent_workflow_status",
            {"workflow_run_id": payload["workflow_run_id"]},
            context={"session_id": session_id, "run_id": run_id},
        )
    )
    assert status["workflow_run_id"] == payload["workflow_run_id"]
    assert "phases" in status


def test_rerun_failed_workflow_phase_reenqueues_existing_workflow(monkeypatch) -> None:
    store = _store()
    session_id, run_id = _new_session(store)
    workflow_yaml = """
id: audit
name: Audit
phases:
  - id: inspect
    kind: single
    agent: explorer
    prompt: Inspect repository
"""
    workflow_run = store.workflow_runs.create(
        spec_id="audit",
        parent_session_id=session_id,
        parent_run_id=run_id,
        metadata={"workflow_yaml": workflow_yaml},
    )
    phase_run = store.workflow_phase_runs.create(
        workflow_run_id=workflow_run["id"],
        phase_id="inspect",
        kind="single",
        agent="explorer",
    )
    store.workflow_phase_runs.update(
        phase_run["id"],
        status="failed",
        outputs=["failed"],
        finished=True,
    )
    store.workflow_runs.update(workflow_run["id"], status="failed", finished=True)
    enqueued: list[tuple[str, str]] = []

    class FakeQueue:
        def enqueue(self, queued_run_id: str, kind: str, coroutine_factory, metadata=None):
            enqueued.append((queued_run_id, kind))
            return {"run_id": queued_run_id, "kind": kind}

    import app.agent_framework.tool_modules.collaboration as collaboration

    monkeypatch.setattr(collaboration, "_BACKGROUND_QUEUE", FakeQueue(), raising=False)

    payload = json.loads(
        create_default_registry().invoke(
            "rerun_failed_workflow_phase",
            {
                "workflow_run_id": workflow_run["id"],
                "phase_run_id": phase_run["id"],
            },
            context={
                "session_id": session_id,
                "run_id": run_id,
                "approval_granted": True,
                "approval_id": "appr-rerun",
            },
        )
    )

    assert payload["status"] == "queued"
    assert enqueued == [(workflow_run["id"], "workflow")]
    assert store.workflow_runs.get(workflow_run["id"])["status"] == "queued"
    assert store.workflow_phase_runs.get(phase_run["id"])["status"] == "queued"
