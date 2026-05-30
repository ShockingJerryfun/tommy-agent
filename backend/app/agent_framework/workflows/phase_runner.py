"""Workflow phase execution helper."""

from __future__ import annotations

from ..runtime.background_tasks import CancellationToken
from ..storage import PostgresAgentStore
from ..workers import WorkerPool, WorkerResult, WorkerRunner, WorkerTask


class PhaseRunner:
    def __init__(
        self,
        store: PostgresAgentStore,
        *,
        worker_runner: WorkerRunner | None = None,
        max_concurrency: int = 4,
    ) -> None:
        self.store = store
        self._worker_runner = worker_runner
        self._max_concurrency = max_concurrency

    async def run(
        self,
        worker_tasks: list[WorkerTask],
        *,
        cancellation_token: CancellationToken,
    ) -> list[WorkerResult]:
        cancellation_token.raise_if_cancelled()
        results: list[WorkerResult | None] = [None] * len(worker_tasks)
        uncached_tasks: list[WorkerTask] = []
        uncached_indexes: list[int] = []
        for index, task in enumerate(worker_tasks):
            cached = self._cached_result(task)
            if cached is None:
                uncached_tasks.append(task)
                uncached_indexes.append(index)
            else:
                results[index] = cached

        if uncached_tasks:
            fresh_results = await WorkerPool(
                store=self.store,
                runner=self._worker_runner,
                max_concurrency=self._max_concurrency,
            ).run(uncached_tasks)
            for index, result in zip(uncached_indexes, fresh_results, strict=True):
                results[index] = result
        cancellation_token.raise_if_cancelled()
        return [result for result in results if result is not None]

    def _cached_result(self, task: WorkerTask) -> WorkerResult | None:
        input_hash = str(task.metadata.get("input_hash") or "")
        cached = self.store.workflow_worker_runs.get_completed_by_input_hash(input_hash)
        if cached is None:
            return None
        return WorkerResult(
            task_id=task.id,
            subagent_id=str(cached.get("subagent_run_id") or ""),
            child_session_id=str(cached.get("child_session_id") or ""),
            role_id=task.role_id,
            status="completed",
            final_response=str(cached.get("output") or ""),
            metadata={
                **(cached.get("metadata") or {}),
                **task.metadata,
                "cache_hit": True,
                "cached_worker_run_id": cached["id"],
            },
        )
