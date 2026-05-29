"""Tool integration tests for the multi-agent runtime."""

from __future__ import annotations

import json
import uuid

from app.agent_framework.storage import PostgresAgentStore
from app.agent_framework.subagents import registry_for_role
from app.agent_framework.tool_runtime import create_default_registry
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
            },
        )
    )

    assert payload["status"] == "queued"
    assert payload["team_id"].startswith("team-")
    assert payload["task_count"] == 1
    assert store.agent_teams.get(payload["team_id"]) is not None


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
