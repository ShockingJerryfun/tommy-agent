"""Declarative Workflow Runtime MVP tests."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.agent_framework.storage import PostgresAgentStore
from app.agent_framework.workers import WorkerResult, WorkerTask
from app.agent_framework.workflows import (
    WorkflowRuntime,
    load_workflow_spec,
    workflow_summary_markdown,
)


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
        input="workflow",
        run_id=run_id,
        status="running",
    )
    return session_id, run_id


def _write_spec(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_load_valid_yaml_workflow_spec(tmp_path: Path) -> None:
    spec = load_workflow_spec(
        _write_spec(
            tmp_path / "workflow.yaml",
            """
id: repo_test_gap_audit
name: Repository Test Gap Audit
description: Audit modules for missing tests.
max_concurrency: 4
budget:
  max_workers: 20
  max_wall_seconds: 900
inputs:
  modules:
    - backend/app/agent_framework/graph
    - backend/app/agent_framework/subagents
phases:
  - id: inspect_modules
    kind: fanout
    agent: explorer
    input: inputs.modules
    prompt: |
      Inspect this module:
      {{ item }}
  - id: synthesize
    kind: reduce
    agent: architect
    input: phases.inspect_modules.outputs
    prompt: |
      Produce a plan from:
      {{ item }}
""",
        )
    )

    assert spec.id == "repo_test_gap_audit"
    assert spec.max_concurrency == 4
    assert spec.budget.max_workers == 20
    assert [phase.kind for phase in spec.phases] == ["fanout", "reduce"]


def test_reject_invalid_workflow_spec(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported phase kind"):
        load_workflow_spec(
            _write_spec(
                tmp_path / "bad.yaml",
                """
id: bad
name: Bad
phases:
  - id: run_code
    kind: script
    agent: explorer
    prompt: no
""",
            )
        )


@pytest.mark.asyncio
async def test_run_fanout_reduce_workflow_with_fake_workers(tmp_path: Path) -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)
    calls: list[WorkerTask] = []

    async def runner(task: WorkerTask) -> WorkerResult:
        calls.append(task)
        return WorkerResult(
            task_id=task.id,
            subagent_id=f"sub-{len(calls)}",
            child_session_id=f"child-{len(calls)}",
            role_id=task.role_id,
            status="completed",
            final_response=f"{task.role_id}: {task.task}",
            score=0.8,
        )

    spec = load_workflow_spec(
        _write_spec(
            tmp_path / "workflow.yaml",
            """
id: audit
name: Audit
max_concurrency: 2
budget:
  max_workers: 5
inputs:
  modules:
    - graph
    - subagents
phases:
  - id: inspect
    kind: fanout
    agent: explorer
    input: inputs.modules
    prompt: Inspect {{ item }}
  - id: synthesize
    kind: reduce
    agent: architect
    input: phases.inspect.outputs
    prompt: Summarize {{ item }}
""",
        )
    )

    result = await WorkflowRuntime(store, worker_runner=runner).run(
        spec,
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
    )

    assert result.status == "completed"
    assert result.workflow_run_id
    assert len(calls) == 3
    assert [call.role_id for call in calls] == ["explorer", "explorer", "architect"]
    assert all(call.child_context is not None for call in calls)
    assert {call.child_context.workflow_run_id for call in calls if call.child_context} == {
        result.workflow_run_id
    }
    assert {call.child_context.workflow_phase_id for call in calls if call.child_context} == {
        "inspect",
        "synthesize",
    }
    run = store.workflow_runs.get(result.workflow_run_id)
    assert run is not None
    assert run["status"] == "completed"
    assert "architect:" in result.summary


@pytest.mark.asyncio
async def test_failed_workflow_worker_is_captured(tmp_path: Path) -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)

    async def runner(task: WorkerTask) -> WorkerResult:
        if "bad" in task.task:
            raise RuntimeError("bad module")
        return WorkerResult(
            task_id=task.id,
            subagent_id="sub-ok",
            child_session_id="child-ok",
            role_id=task.role_id,
            status="completed",
            final_response="ok",
        )

    spec = load_workflow_spec(
        _write_spec(
            tmp_path / "workflow.yaml",
            """
id: audit_fail
name: Audit Fail
budget:
  max_workers: 4
inputs:
  modules:
    - good
    - bad
phases:
  - id: inspect
    kind: fanout
    agent: explorer
    input: inputs.modules
    prompt: Inspect {{ item }}
""",
        )
    )

    result = await WorkflowRuntime(store, worker_runner=runner).run(
        spec,
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
    )

    assert result.status == "failed"
    assert "worker error: bad module" in result.summary
    workers = store.workflow_worker_runs.list_for_run(result.workflow_run_id)
    assert [worker["status"] for worker in workers] == ["completed", "failed"]


@pytest.mark.asyncio
async def test_max_workers_budget_is_enforced(tmp_path: Path) -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)

    async def runner(task: WorkerTask) -> WorkerResult:
        return WorkerResult(
            task_id=task.id,
            subagent_id="sub",
            child_session_id="child",
            role_id=task.role_id,
            status="completed",
            final_response="ok",
        )

    spec = load_workflow_spec(
        _write_spec(
            tmp_path / "workflow.yaml",
            """
id: budget
name: Budget
budget:
  max_workers: 1
inputs:
  modules:
    - one
    - two
phases:
  - id: inspect
    kind: fanout
    agent: explorer
    input: inputs.modules
    prompt: Inspect {{ item }}
""",
        )
    )

    with pytest.raises(ValueError, match="max_workers"):
        await WorkflowRuntime(store, worker_runner=runner).run(
            spec,
            parent_session_id=parent_session_id,
            parent_run_id=parent_run_id,
        )


def test_workflow_summary_is_bounded() -> None:
    summary = workflow_summary_markdown(
        workflow_name="Audit",
        status="completed",
        phase_outputs={"inspect": ["x" * 5000]},
        max_chars=500,
    )

    assert len(summary) <= 500
    assert "x" * 1000 not in summary
