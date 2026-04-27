"""Asyncio in-proc maintenance scheduler.

A small, dependency-free scheduler that runs a list of
:class:`MaintenanceJob` callables on fixed intervals. The scheduler
is started from the FastAPI lifespan and cancelled cleanly on
shutdown. Each job runs inside a ``try/except`` and never propagates
errors out of the scheduler loop.

Default jobs (see :func:`default_maintenance_jobs`):

- ``memory.apply_decay`` — soft-decays unused memories every 6 hours.
- ``approvals.cleanup_stale`` — rejects pendings older than the TTL
  every 30 minutes (delegates to the same hook bundle).
- ``skills.forge_nightly`` — runs the Skill Forge mining + shadow
  validation pipeline every 24 hours.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("tommy.observability.maintenance")


JobBody = Callable[[], Awaitable[None] | None]


@dataclass
class MaintenanceJob:
    name: str
    interval_seconds: float
    body: JobBody
    enabled: bool = True


class MaintenanceScheduler:
    def __init__(self, jobs: list[MaintenanceJob] | None = None) -> None:
        self.jobs: list[MaintenanceJob] = list(jobs or [])
        self._tasks: list[asyncio.Task[None]] = []
        self._stop_event = asyncio.Event()
        self.last_outcomes: dict[str, str] = {}

    def add(self, job: MaintenanceJob) -> None:
        self.jobs.append(job)

    async def run_once(self, name: str) -> str:
        """Run a single job synchronously (testing aid)."""

        for job in self.jobs:
            if job.name == name:
                return await self._invoke(job)
        raise KeyError(f"unknown maintenance job: {name}")

    async def start(self) -> None:
        if self._tasks:
            return
        self._stop_event.clear()
        for job in self.jobs:
            if job.enabled:
                self._tasks.append(asyncio.create_task(self._loop(job)))

    async def stop(self) -> None:
        self._stop_event.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                continue
        self._tasks.clear()

    async def _loop(self, job: MaintenanceJob) -> None:
        try:
            while not self._stop_event.is_set():
                await self._invoke(job)
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=job.interval_seconds
                    )
                except TimeoutError:
                    continue
        except asyncio.CancelledError:
            return

    async def _invoke(self, job: MaintenanceJob) -> str:
        try:
            result = job.body()
            if asyncio.iscoroutine(result):
                await result
            outcome = "ok"
        except Exception as exc:  # noqa: BLE001 — never raise out.
            logger.warning("maintenance job %s failed: %s", job.name, exc)
            outcome = f"error: {type(exc).__name__}"
        self.last_outcomes[job.name] = outcome
        return outcome


def _distinct_agent_ids(store: Any) -> list[str]:
    """Best-effort lookup of distinct agent_ids known to the store.

    Falls back to an empty list (callers default to ``["default"]``)
    when the schema/table isn't available.
    """
    try:
        connector = getattr(store, "_connector", None)
        if connector is None:
            return []
        with connector.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT agent_id FROM sessions WHERE agent_id IS NOT NULL"
            ).fetchall()
        return [row[0] for row in rows if row and row[0]]
    except Exception:  # noqa: BLE001 — never raise out of maintenance.
        return []


# --------------------------------------------------------------------- defaults


def default_maintenance_jobs(store: Any) -> list[MaintenanceJob]:
    """Return the canonical maintenance bundle bound to ``store``.

    Jobs avoid heavy imports at module load — they import the relevant
    pipelines lazily so this module stays cheap to import.
    """

    async def memory_decay() -> None:
        from ..memory_platform import get_default_memory_provider

        provider = get_default_memory_provider(store)
        agent_ids = _distinct_agent_ids(store)
        for agent_id in agent_ids or ["default"]:
            provider.forget(agent_id=agent_id)

    async def approvals_cleanup() -> None:
        from ..extensions import (
            HookContext,
            HookPhase,
            HookRegistry,
            install_builtin_hooks,
        )

        registry = HookRegistry()
        install_builtin_hooks(registry, store=store)
        registry.dispatch(HookPhase.RUN_END, HookContext(phase=HookPhase.RUN_END))
        registry.shutdown()

    async def skills_forge_nightly() -> None:
        try:
            from ..skills_forge import SkillForge, run_nightly
        except Exception:  # noqa: BLE001 — optional pipeline.
            return
        agent_ids = _distinct_agent_ids(store) or ["default"]
        for agent_id in agent_ids:
            forge = SkillForge(store=store)
            run_nightly(agent_id=agent_id, forge=forge)

    return [
        MaintenanceJob(
            name="memory.apply_decay",
            interval_seconds=6 * 60 * 60,
            body=memory_decay,
        ),
        MaintenanceJob(
            name="approvals.cleanup_stale",
            interval_seconds=30 * 60,
            body=approvals_cleanup,
        ),
        MaintenanceJob(
            name="skills.forge_nightly",
            interval_seconds=24 * 60 * 60,
            body=skills_forge_nightly,
        ),
    ]
