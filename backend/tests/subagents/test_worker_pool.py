"""WorkerPool tests for bounded child-agent execution."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from app.agent_framework.storage import PostgresAgentStore
from app.agent_framework.subagents import BestOfNMerger, SubagentDelegator, SubagentRole
from app.agent_framework.tool_runtime import ToolRegistry
from app.agent_framework.workers import WorkerPool, WorkerResult, WorkerTask
from app.agent_framework.workers.context import ChildRunContext


def _store() -> PostgresAgentStore:
    store = PostgresAgentStore()
    store.reset_for_tests()
    return store


def _new_session(store: PostgresAgentStore) -> tuple[str, str]:
    session_id = f"sess-{uuid.uuid4().hex[:10]}"
    store.create_session(session_id=session_id, agent_id="default", title="t")
    run_id = f"run-{uuid.uuid4().hex[:10]}"
    return session_id, run_id


def _task(
    task_id: str,
    *,
    parent_session_id: str = "sess",
    parent_run_id: str = "run",
) -> WorkerTask:
    return WorkerTask(
        id=task_id,
        role_id="researcher",
        task=f"do {task_id}",
        reason="test",
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        agent_id="default",
    )


@pytest.mark.asyncio
async def test_worker_pool_respects_max_concurrency_and_preserves_order() -> None:
    active = 0
    max_active = 0

    async def runner(task: WorkerTask) -> WorkerResult:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        return WorkerResult(
            task_id=task.id,
            subagent_id=f"sub-{task.id}",
            child_session_id=f"child-{task.id}",
            role_id=task.role_id,
            status="completed",
            final_response=f"result {task.id}",
        )

    tasks = [_task("a"), _task("b"), _task("c"), _task("d")]
    results = await WorkerPool(runner=runner, max_concurrency=2).run(tasks)

    assert [result.task_id for result in results] == ["a", "b", "c", "d"]
    assert [result.final_response for result in results] == [
        "result a",
        "result b",
        "result c",
        "result d",
    ]
    assert max_active == 2


@pytest.mark.asyncio
async def test_worker_pool_records_failed_worker_as_result() -> None:
    async def runner(task: WorkerTask) -> WorkerResult:
        if task.id == "bad":
            raise RuntimeError("worker exploded")
        return WorkerResult(
            task_id=task.id,
            subagent_id=f"sub-{task.id}",
            child_session_id=f"child-{task.id}",
            role_id=task.role_id,
            status="completed",
            final_response=f"ok {task.id}",
        )

    results = await WorkerPool(runner=runner, max_concurrency=2).run(
        [_task("good"), _task("bad"), _task("later")]
    )

    assert [result.status for result in results] == ["completed", "failed", "completed"]
    assert results[1].task_id == "bad"
    assert "worker exploded" in results[1].final_response


@pytest.mark.asyncio
async def test_worker_pool_short_circuits_when_parent_run_is_stopped() -> None:
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

    async def runner(task: WorkerTask) -> WorkerResult:
        nonlocal called
        called = True
        return WorkerResult(
            task_id=task.id,
            subagent_id="sub",
            child_session_id="child",
            role_id=task.role_id,
            status="completed",
            final_response="should not run",
        )

    results = await WorkerPool(store=store, runner=runner).run(
        [_task("stopped", parent_session_id=parent_session_id, parent_run_id=parent_run_id)]
    )

    assert called is False
    assert results[0].status == "stopped"
    assert results[0].subagent_id == ""
    assert results[0].child_session_id == ""


@pytest.mark.asyncio
async def test_worker_pool_does_not_treat_approval_interruption_as_stop() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)
    store.create_run(
        session_id=parent_session_id,
        agent_id="default",
        input="needs approval",
        run_id=parent_run_id,
        status="interrupted",
    )
    store.start_run(parent_session_id, run_id=parent_run_id)
    store.finish_run(parent_session_id, run_id=parent_run_id, status="stopped")
    called = False

    async def runner(task: WorkerTask) -> WorkerResult:
        nonlocal called
        called = True
        return WorkerResult(
            task_id=task.id,
            subagent_id="sub",
            child_session_id="child",
            role_id=task.role_id,
            status="completed",
            final_response="ran after approval",
        )

    results = await WorkerPool(store=store, runner=runner).run(
        [_task("approved", parent_session_id=parent_session_id, parent_run_id=parent_run_id)]
    )

    assert called is True
    assert results[0].status == "completed"
    assert results[0].final_response == "ran after approval"


@pytest.mark.asyncio
async def test_worker_pool_default_runner_uses_subagent_delegator() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)

    def fake_subagent_runner(
        prompt: str,
        registry: ToolRegistry,
        role: SubagentRole,
        thread_config: dict[str, Any],
    ) -> dict[str, Any]:
        return {"final_response": f"{role.id} done", "status": "completed"}

    delegator = SubagentDelegator(store, runner=fake_subagent_runner)
    results = await WorkerPool(store=store, delegator=delegator).run(
        [_task("delegated", parent_session_id=parent_session_id, parent_run_id=parent_run_id)]
    )

    assert results[0].status == "completed"
    assert results[0].final_response == "researcher done"
    assert store.subagent_runs.list_for_session(parent_session_id)


@pytest.mark.asyncio
async def test_worker_pool_passes_supplied_child_context_to_delegator() -> None:
    context = ChildRunContext(
        parent_session_id="sess-parent",
        parent_run_id="run-parent",
        subagent_role="reviewer",
        team_id="team-1",
    )
    captured: dict[str, Any] = {}

    class CapturingDelegator:
        def dispatch(self, **kwargs: Any):
            captured.update(kwargs)
            from app.agent_framework.subagents import SubagentResult

            return SubagentResult(
                subagent_id="sub-1",
                child_session_id="child-1",
                role=kwargs["role_id"],
                status="completed",
                final_response="ok",
            )

    task = WorkerTask(
        id="task-1",
        role_id="reviewer",
        task="review",
        reason="test",
        parent_session_id="sess-parent",
        parent_run_id="run-parent",
        child_context=context,
        approval_id="approval-1",
    )

    results = await WorkerPool(delegator=CapturingDelegator()).run([task])  # type: ignore[arg-type]

    assert results[0].status == "completed"
    assert captured["child_context"] is context
    assert captured["approval_id"] == "approval-1"


@pytest.mark.asyncio
async def test_worker_pool_derives_child_context_before_custom_runner() -> None:
    seen: list[WorkerTask] = []

    async def runner(task: WorkerTask) -> WorkerResult:
        seen.append(task)
        assert task.child_context is not None
        assert task.child_context.team_id == "team-1"
        assert task.child_context.team_task_id == "team-task-1"
        assert task.child_context.approval_id == "approval-1"
        return WorkerResult(
            task_id=task.id,
            subagent_id="sub",
            child_session_id="child",
            role_id=task.role_id,
            status="completed",
            final_response="ok",
        )

    task = WorkerTask(
        id="team-task-1",
        role_id="reviewer",
        task="review",
        reason="test",
        parent_session_id="sess-parent",
        parent_run_id="run-parent",
        metadata={"team_id": "team-1", "team_task_id": "team-task-1"},
        approval_id="approval-1",
    )

    await WorkerPool(runner=runner).run([task])

    assert seen[0].child_context is not None


def test_best_of_n_behavior_still_works_after_worker_pool_addition() -> None:
    store = _store()
    parent_session_id, parent_run_id = _new_session(store)

    def runner(*_: Any, **__: Any) -> dict[str, Any]:
        return {"final_response": "evidence https://example.com", "status": "completed"}

    merged = BestOfNMerger(store, SubagentDelegator(store, runner=runner)).run(
        task="t",
        role_id="researcher",
        parent_session_id=parent_session_id,
        parent_run_id=parent_run_id,
        n=2,
    )

    assert merged.status == "completed"
    assert len(merged.attempts) == 2
