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
        results = await WorkerPool(
            store=self.store,
            runner=self._worker_runner,
            max_concurrency=self._max_concurrency,
        ).run(worker_tasks)
        cancellation_token.raise_if_cancelled()
        return results
