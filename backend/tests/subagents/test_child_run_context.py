"""ChildRunContext inheritance and lineage tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.agent_framework.workers.context import ChildRunContext, derive_child_context


def test_child_context_inherits_working_directory_from_frontend_settings() -> None:
    context = derive_child_context(
        parent_session_id="sess-1",
        parent_run_id="run-1",
        parent_metadata={
            "frontend_settings": {
                "workingDirectory": "/repo",
                "commandScope": "restricted",
            }
        },
        role_id="reviewer",
    )

    assert context.working_directory == "/repo"
    assert context.command_scope == "restricted"
    assert context.subagent_role == "reviewer"
    assert context.is_child is True


def test_child_context_inherits_restricted_command_scope() -> None:
    context = derive_child_context(
        parent_session_id="sess-1",
        parent_run_id="run-1",
        parent_metadata={"frontend_settings": {"commandScope": "restricted"}},
    )

    assert context.command_scope == "restricted"


def test_child_context_rejects_unrestricted_scope_widening() -> None:
    context = derive_child_context(
        parent_session_id="sess-1",
        parent_run_id="run-1",
        parent_metadata={"frontend_settings": {"commandScope": "restricted"}},
        overrides={"command_scope": "unrestricted"},
    )

    assert context.command_scope == "restricted"


def test_child_context_rejects_permission_widening() -> None:
    context = derive_child_context(
        parent_session_id="sess-1",
        parent_run_id="run-1",
        parent_metadata={"permission_mode": "read_only"},
        overrides={"permission_mode": "workspace_write"},
    )

    assert context.permission_mode == "read_only"


def test_child_context_depth_increments_from_parent_metadata() -> None:
    context = derive_child_context(
        parent_session_id="sess-1",
        parent_run_id="run-1",
        parent_metadata={"depth": 2},
    )

    assert context.depth == 3


def test_child_context_lineage_metadata_includes_team_and_workflow_fields() -> None:
    context = derive_child_context(
        parent_session_id="sess-1",
        parent_run_id="run-1",
        parent_agent_id="agent-1",
        parent_metadata={
            "team_id": "team-1",
            "team_task_id": "task-1",
            "workflow_run_id": "workflow-1",
            "phase_run_id": "phase-run-1",
            "workflow_phase_id": "phase-1",
            "approval_id": "approval-1",
        },
        role_id="tester",
    )

    assert context.lineage_metadata() == {
        "parent_session_id": "sess-1",
        "parent_run_id": "run-1",
        "parent_agent_id": "agent-1",
        "subagent_role": "tester",
        "team_id": "team-1",
        "team_task_id": "task-1",
        "workflow_run_id": "workflow-1",
        "phase_run_id": "phase-run-1",
        "workflow_phase_id": "phase-1",
    }
    assert context.as_metadata()["approval_id"] == "approval-1"
    assert "approval_id" not in context.lineage_metadata()


def test_child_context_is_frozen() -> None:
    context = ChildRunContext(parent_session_id="sess-1", parent_run_id="run-1")

    with pytest.raises(FrozenInstanceError):
        context.parent_run_id = "run-2"


def test_direct_child_context_metadata_mirrors_runtime_frontend_settings() -> None:
    context = ChildRunContext(
        parent_session_id="sess-1",
        parent_run_id="run-1",
        working_directory="/repo",
        command_scope="restricted",
        model="deepseek-chat",
    )

    assert context.as_metadata()["frontend_settings"] == {
        "workingDirectory": "/repo",
        "commandScope": "restricted",
        "model": "deepseek-chat",
    }
