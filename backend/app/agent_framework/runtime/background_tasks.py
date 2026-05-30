"""In-process background execution queue for team and workflow runs."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


class CancellationToken:
    def __init__(self) -> None:
        self._cancelled = False
        self._reason = ""

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def reason(self) -> str:
        return self._reason

    def cancel(self, reason: str = "") -> None:
        self._cancelled = True
        self._reason = reason

    def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise asyncio.CancelledError(self._reason)


@dataclass(frozen=True)
class BackgroundRunHandle:
    run_id: str
    kind: str
    task: asyncio.Task[Any]
    metadata: dict[str, Any] = field(default_factory=dict)


StatusWriter = Callable[[str, str, dict[str, Any]], Awaitable[None] | None]
CoroutineFactory = Callable[[CancellationToken], Awaitable[Any]]
OrphanProvider = Callable[[], list[dict[str, Any]]]


class BackgroundRunQueue:
    def __init__(
        self,
        *,
        status_writer: StatusWriter | None = None,
        orphan_provider: OrphanProvider | None = None,
    ) -> None:
        self._status_writer = status_writer
        self._orphan_provider = orphan_provider
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._tokens: dict[str, CancellationToken] = {}
        self._statuses: dict[str, dict[str, Any]] = {}

    def enqueue(
        self,
        run_id: str,
        kind: str,
        coroutine_factory: CoroutineFactory,
        metadata: dict[str, Any] | None = None,
    ) -> BackgroundRunHandle:
        if run_id in self._tasks and not self._tasks[run_id].done():
            raise ValueError(f"background run already active: {run_id}")
        token = CancellationToken()
        run_metadata = dict(metadata or {})
        self._tokens[run_id] = token
        self._set_status(run_id, kind, "queued", run_metadata)
        task = asyncio.create_task(
            self._run(run_id, kind, token, coroutine_factory, run_metadata)
        )
        self._tasks[run_id] = task
        return BackgroundRunHandle(run_id=run_id, kind=kind, task=task, metadata=run_metadata)

    def get_status(self, run_id: str) -> dict[str, Any]:
        if run_id in self._statuses:
            return dict(self._statuses[run_id])
        return {"run_id": run_id, "status": "unknown"}

    def cancel(self, run_id: str, reason: str = "") -> bool:
        token = self._tokens.get(run_id)
        task = self._tasks.get(run_id)
        if token is None or task is None or task.done():
            return False
        token.cancel(reason)
        self._set_status(
            run_id,
            str(self._statuses.get(run_id, {}).get("kind") or ""),
            "cancelled",
            {"reason": reason},
        )
        task.cancel(reason)
        return True

    def list_active(self) -> list[dict[str, Any]]:
        return [
            self.get_status(run_id)
            for run_id, task in self._tasks.items()
            if not task.done()
        ]

    def mark_orphans_interrupted(self) -> int:
        if self._orphan_provider is None:
            return 0
        rows = self._orphan_provider()
        for row in rows:
            run_id = str(row.get("id") or row.get("run_id") or "")
            if not run_id:
                continue
            kind = str(row.get("kind") or "")
            metadata = {"reason": "Background process restarted while run was active."}
            self._set_status(run_id, kind, "interrupted", metadata, sync=True)
        return len(rows)

    async def _run(
        self,
        run_id: str,
        kind: str,
        token: CancellationToken,
        coroutine_factory: CoroutineFactory,
        metadata: dict[str, Any],
    ) -> Any:
        self._set_status(run_id, kind, "running", metadata)
        try:
            token.raise_if_cancelled()
            result = await coroutine_factory(token)
        except asyncio.CancelledError:
            self._set_status(
                run_id,
                kind,
                "cancelled",
                {"reason": token.reason or "cancelled"},
            )
            raise
        except Exception as exc:
            self._set_status(
                run_id,
                kind,
                "failed",
                {"error_type": type(exc).__name__, "error_message": str(exc)},
            )
            raise
        self._set_status(run_id, kind, "completed", metadata)
        return result

    def _set_status(
        self,
        run_id: str,
        kind: str,
        status: str,
        metadata: dict[str, Any],
        *,
        sync: bool = False,
    ) -> None:
        current = dict(self._statuses.get(run_id) or {})
        current.update(metadata)
        current.update(
            {
                "run_id": run_id,
                "kind": kind or current.get("kind", ""),
                "status": status,
            }
        )
        self._statuses[run_id] = current
        if self._status_writer is None:
            return
        result = self._status_writer(run_id, status, current)
        if inspect.isawaitable(result):
            if sync:
                asyncio.run(result)
            else:
                asyncio.create_task(result)
