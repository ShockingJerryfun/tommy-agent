from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from app.agent_framework.runtime.background_tasks import CancellationToken
from app.agent_framework.storage import PostgresAgentStore
from app.agent_framework.workers import WorkerResult, WorkerTask
from app.agent_framework.workflows import WorkflowRuntime, load_workflow_spec


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


@pytest.mark.asyncio
async def test_workflow_runtime_honors_cancellation_between_phases(tmp_path: Path) -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)
    token = CancellationToken()

    async def runner(task: WorkerTask) -> WorkerResult:
        token.cancel("stop before next phase")
        return WorkerResult(
            task_id=task.id,
            subagent_id="sub-1",
            child_session_id="child-1",
            role_id=task.role_id,
            status="completed",
            final_response="ok",
        )

    spec = load_workflow_spec(
        _write_spec(
            tmp_path / "workflow.yaml",
            """
id: cancellable
name: Cancellable
phases:
  - id: first
    kind: single
    agent: explorer
    prompt: First
  - id: second
    kind: single
    agent: explorer
    prompt: Second
""",
        )
    )

    with pytest.raises(asyncio.CancelledError):
        await WorkflowRuntime(store, worker_runner=runner).run(
            spec,
            parent_session_id=parent_session_id,
            parent_run_id=parent_run_id,
            cancellation_token=token,
        )

    run = store.workflow_runs.list_for_parent_run(parent_run_id)[0]
    phases = store.workflow_phase_runs.list_for_run(run["id"])
    assert run["status"] == "stopped"
    assert [phase["phase_id"] for phase in phases] == ["first"]


@pytest.mark.asyncio
async def test_workflow_runtime_timeout_fails_cleanly(tmp_path: Path) -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)

    async def runner(task: WorkerTask) -> WorkerResult:
        await asyncio.sleep(0.05)
        return WorkerResult(
            task_id=task.id,
            subagent_id="sub-slow",
            child_session_id="child-slow",
            role_id=task.role_id,
            status="completed",
            final_response="late",
        )

    spec = load_workflow_spec(
        _write_spec(
            tmp_path / "workflow.yaml",
            """
id: timeout
name: Timeout
budget:
  max_wall_seconds: 0.01
phases:
  - id: slow
    kind: single
    agent: explorer
    prompt: Slow
""",
        )
    )

    result = await WorkflowRuntime(store, worker_runner=runner).run(
        spec,
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
    )

    assert result.status == "failed"
    assert "timed out" in result.summary
    assert store.workflow_runs.get(result.workflow_run_id)["status"] == "failed"


def test_workflow_runtime_module_does_not_expose_sync_thread_bridge() -> None:
    import app.agent_framework.tool_modules.collaboration as collaboration

    assert not hasattr(collaboration, "_run_coro_sync")


@pytest.mark.asyncio
async def test_workflow_runtime_resumes_from_failed_phase(tmp_path: Path) -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)
    calls: list[str] = []

    async def first_runner(task: WorkerTask) -> WorkerResult:
        calls.append(task.task)
        status = "failed" if "Second" in task.task else "completed"
        return WorkerResult(
            task_id=task.id,
            subagent_id=f"sub-{task.id}",
            child_session_id=f"child-{task.id}",
            role_id=task.role_id,
            status=status,
            final_response=f"{status} {task.task}",
        )

    spec = load_workflow_spec(
        _write_spec(
            tmp_path / "resume.yaml",
            """
id: resume
name: Resume
phases:
  - id: first
    kind: single
    agent: explorer
    prompt: First
  - id: second
    kind: single
    agent: explorer
    prompt: Second
""",
        )
    )

    result = await WorkflowRuntime(store, worker_runner=first_runner).run(
        spec,
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
    )
    assert result.status == "failed"
    assert calls == ["First", "Second"]

    resumed_calls: list[str] = []

    async def resumed_runner(task: WorkerTask) -> WorkerResult:
        resumed_calls.append(task.task)
        return WorkerResult(
            task_id=task.id,
            subagent_id=f"sub-resumed-{task.id}",
            child_session_id=f"child-resumed-{task.id}",
            role_id=task.role_id,
            status="completed",
            final_response=f"resumed {task.task}",
        )

    resumed = await WorkflowRuntime(store, worker_runner=resumed_runner).run(
        spec,
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        workflow_run_id=result.workflow_run_id,
    )

    assert resumed.status == "completed"
    assert resumed_calls == ["Second"]


@pytest.mark.asyncio
async def test_workflow_runtime_uses_completed_worker_cache(tmp_path: Path) -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)
    calls: list[str] = []

    async def runner(task: WorkerTask) -> WorkerResult:
        calls.append(task.id)
        return WorkerResult(
            task_id=task.id,
            subagent_id=f"sub-{task.id}",
            child_session_id=f"child-{task.id}",
            role_id=task.role_id,
            status="completed",
            final_response="cached output",
            metadata=task.metadata,
        )

    spec = load_workflow_spec(
        _write_spec(
            tmp_path / "cache.yaml",
            """
id: cache
name: Cache
phases:
  - id: inspect
    kind: single
    agent: explorer
    prompt: Inspect
""",
        )
    )

    await WorkflowRuntime(store, worker_runner=runner).run(
        spec,
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
    )
    second = await WorkflowRuntime(store, worker_runner=runner).run(
        spec,
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
    )

    workers = store.workflow_worker_runs.list_for_run(second.workflow_run_id)
    assert len(calls) == 1
    assert workers[0]["cache_hit"] is True
    assert workers[0]["output"] == "cached output"
