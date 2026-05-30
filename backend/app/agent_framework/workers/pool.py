"""Bounded concurrent worker pool built on ChildRunService."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Sequence
from dataclasses import replace

from ..storage import PostgresAgentStore
from ..subagents import SubagentDelegator
from ..subagents.delegate import SubagentResult
from .child_run_service import ChildRunRequest, ChildRunService
from .context import derive_child_context
from .runner import WorkerRunner
from .types import WorkerResult, WorkerTask


class WorkerPool:
    """Run child-agent tasks with bounded concurrency and structured failures."""

    def __init__(
        self,
        store: PostgresAgentStore | None = None,
        *,
        delegator: SubagentDelegator | None = None,
        runner: WorkerRunner | None = None,
        max_concurrency: int = 4,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if runner is None and delegator is None and store is None:
            raise ValueError("WorkerPool requires a runner, delegator, or store")
        self.store = store
        self._delegator = delegator
        self._runner = runner
        self._max_concurrency = max_concurrency

    async def run(self, tasks: Sequence[WorkerTask]) -> list[WorkerResult]:
        semaphore = asyncio.Semaphore(self._max_concurrency)
        indexed = [
            self._run_indexed(index, task, semaphore)
            for index, task in enumerate(tasks)
        ]
        results = await asyncio.gather(*indexed)
        return [result for _, result in sorted(results, key=lambda item: item[0])]

    async def _run_indexed(
        self,
        index: int,
        task: WorkerTask,
        semaphore: asyncio.Semaphore,
    ) -> tuple[int, WorkerResult]:
        async with semaphore:
            return index, await self._run_one(task)

    async def _run_one(self, task: WorkerTask) -> WorkerResult:
        task = _ensure_child_context(task)
        if self._parent_run_stopped(task):
            return _stopped_result(task)
        try:
            result = await self._execute(task)
        except Exception as exc:  # noqa: BLE001 - worker failures are returned, not raised.
            return _failed_result(task, exc)
        return _coerce_result(task, result)

    async def _execute(self, task: WorkerTask) -> WorkerResult | SubagentResult:
        if self._runner is not None:
            if inspect.iscoroutinefunction(self._runner):
                return await self._runner(task)
            result = await asyncio.to_thread(self._runner, task)
            if inspect.isawaitable(result):
                return await result
            return result
        if self._delegator is None:
            if self.store is None:
                raise RuntimeError("WorkerPool has no runner, delegator, or store")
            return await asyncio.to_thread(
                ChildRunService(self.store).run,
                ChildRunRequest(
                    task=task.task,
                    role_id=task.role_id,
                    context=task.child_context,
                    attempt_index=task.attempt_index,
                    reason=task.reason,
                    task_id=task.id,
                ),
            )
        return await asyncio.to_thread(
            self._delegator.dispatch,
            task=task.task,
            role_id=task.role_id,
            parent_session_id=task.parent_session_id,
            parent_run_id=task.parent_run_id,
            agent_id=task.agent_id,
            reason=task.reason,
            attempt_index=task.attempt_index,
            approval_id=task.approval_id,
            child_context=task.child_context,
            parent_metadata=task.metadata,
        )

    def _parent_run_stopped(self, task: WorkerTask) -> bool:
        if self.store is None:
            return False
        return bool(
            self.store.explicit_stop_requested(
                session_id=task.parent_session_id,
                run_id=task.parent_run_id,
            )
        )


def _coerce_result(task: WorkerTask, result: WorkerResult | SubagentResult) -> WorkerResult:
    if isinstance(result, WorkerResult):
        return result
    return WorkerResult(
        task_id=task.id,
        subagent_id=result.subagent_id,
        child_session_id=result.child_session_id,
        role_id=result.role,
        status=result.status,
        final_response=result.final_response,
        score=result.score,
        metadata=dict(result.metadata or {}),
    )


def _ensure_child_context(task: WorkerTask) -> WorkerTask:
    if task.child_context is not None:
        return task
    parent_metadata = dict(task.metadata or {})
    if task.approval_id and "approval_id" not in parent_metadata:
        parent_metadata["approval_id"] = task.approval_id
    child_context = derive_child_context(
        parent_session_id=task.parent_session_id,
        parent_run_id=task.parent_run_id,
        parent_agent_id=task.agent_id,
        parent_metadata=parent_metadata,
        role_id=task.role_id,
    )
    return replace(task, child_context=child_context, metadata=parent_metadata)


def _failed_result(task: WorkerTask, exc: Exception) -> WorkerResult:
    return WorkerResult(
        task_id=task.id,
        subagent_id="",
        child_session_id="",
        role_id=task.role_id,
        status="failed",
        final_response=f"worker error: {exc}",
        metadata={"error_type": type(exc).__name__},
    )


def _stopped_result(task: WorkerTask) -> WorkerResult:
    return WorkerResult(
        task_id=task.id,
        subagent_id="",
        child_session_id="",
        role_id=task.role_id,
        status="stopped",
        final_response="",
    )
