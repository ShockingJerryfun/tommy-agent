"""ChildRunContext inheritance and lineage tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.agent_framework.workers.context import (
    ChildRunContext,
    derive_child_context,
    merge_child_parent_metadata,
    parent_metadata_from_runtime_context,
)


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


def test_child_context_narrows_unrestricted_scope_request() -> None:
    context = derive_child_context(
        parent_session_id="sess-1",
        parent_run_id="run-1",
        parent_metadata={"frontend_settings": {"commandScope": "restricted"}},
        overrides={"command_scope": "unrestricted"},
    )

    assert context.command_scope == "restricted"


def test_child_context_narrows_permission_widening_request() -> None:
    context = derive_child_context(
        parent_session_id="sess-1",
        parent_run_id="run-1",
        parent_metadata={"permission_mode": "read_only"},
        overrides={"permission_mode": "workspace_write"},
    )

    assert context.permission_mode == "read_only"


@pytest.mark.parametrize(
    ("parent_mode", "requested_mode", "expected_mode"),
    [
        ("read_only", "test_runner", "read_only"),
        ("test_runner", "workspace_patch", "workspace_patch"),
        ("workspace_write", "workflow_lead", "workflow_lead"),
        ("workflow_lead", "admin", "workflow_lead"),
        ("admin", "danger_full_access", "danger_full_access"),
    ],
)
def test_child_context_narrows_future_permission_modes_by_rank(
    parent_mode: str,
    requested_mode: str,
    expected_mode: str,
) -> None:
    context = derive_child_context(
        parent_session_id="sess-1",
        parent_run_id="run-1",
        parent_metadata={"permission_mode": parent_mode},
        overrides={"permission_mode": requested_mode},
    )

    assert context.permission_mode == expected_mode


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


def test_parent_metadata_from_runtime_context_normalizes_aliases_without_dropping_fields() -> None:
    metadata = parent_metadata_from_runtime_context(
        {
            "session_id": "sess-1",
            "run_id": "run-top",
            "agent_id": "agent-1",
            "approval_id": "approval-1",
            "frontend_settings": {
                "workingDirectory": "/repo/from-settings",
                "commandScope": "restricted",
                "theme": "dark",
            },
            "metadata": {
                "run_id": "run-meta",
                "frontend_settings": {"workingDirectory": "/repo/from-meta"},
                "workingDirectory": "/repo/from-camel",
                "command_scope": "unrestricted",
                "commandScope": "restricted",
                "model": "deepseek-chat",
                "permission_mode": "workspace_write",
                "budget": {"max_turns": 4},
                "depth": 2,
                "team_id": "team-1",
                "team_task_id": "team-task-1",
                "workflow_run_id": "workflow-1",
                "phase_run_id": "phase-run-1",
                "workflow_phase_id": "phase-1",
                "custom": "kept",
            },
        }
    )

    assert metadata["run_id"] == "run-top"
    assert metadata["agent_id"] == "agent-1"
    assert metadata["approval_id"] == "approval-1"
    assert metadata["frontend_settings"]["workingDirectory"] == "/repo/from-camel"
    assert metadata["frontend_settings"]["theme"] == "dark"
    assert metadata["workingDirectory"] == "/repo/from-camel"
    assert metadata["working_directory"] == "/repo/from-camel"
    assert metadata["commandScope"] == "restricted"
    assert metadata["command_scope"] == "restricted"
    assert metadata["model"] == "deepseek-chat"
    assert metadata["permission_mode"] == "workspace_write"
    assert metadata["budget"] == {"max_turns": 4}
    assert metadata["depth"] == 2
    assert metadata["team_id"] == "team-1"
    assert metadata["team_task_id"] == "team-task-1"
    assert metadata["workflow_run_id"] == "workflow-1"
    assert metadata["phase_run_id"] == "phase-run-1"
    assert metadata["workflow_phase_id"] == "phase-1"
    assert metadata["custom"] == "kept"


def test_merge_child_parent_metadata_preserves_existing_fields_and_normalizes_patch() -> None:
    merged = merge_child_parent_metadata(
        {
            "custom": "base",
            "workingDirectory": "/base",
            "frontend_settings": {"workingDirectory": "/base", "theme": "light"},
        },
        {
            "working_directory": "/patch",
            "commandScope": "restricted",
            "frontend_settings": {"commandScope": "restricted"},
            "team_id": "team-1",
        },
    )

    assert merged["custom"] == "base"
    assert merged["team_id"] == "team-1"
    assert merged["workingDirectory"] == "/patch"
    assert merged["working_directory"] == "/patch"
    assert merged["commandScope"] == "restricted"
    assert merged["command_scope"] == "restricted"
    assert merged["frontend_settings"]["workingDirectory"] == "/patch"
    assert merged["frontend_settings"]["commandScope"] == "restricted"
    assert merged["frontend_settings"]["theme"] == "light"


def test_merge_child_parent_metadata_does_not_widen_scope_or_permission() -> None:
    merged = merge_child_parent_metadata(
        {
            "command_scope": "restricted",
            "commandScope": "restricted",
            "permission_mode": "read_only",
        },
        {
            "command_scope": "unrestricted",
            "commandScope": "unrestricted",
            "permission_mode": "danger_full_access",
        },
    )

    assert merged["command_scope"] == "restricted"
    assert merged["commandScope"] == "restricted"
    assert merged["permission_mode"] == "read_only"
