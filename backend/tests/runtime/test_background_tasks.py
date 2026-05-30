from __future__ import annotations

import asyncio

import pytest

from app.agent_framework.runtime.background_tasks import BackgroundRunQueue


@pytest.mark.asyncio
async def test_background_queue_returns_handle_and_persists_success() -> None:
    statuses: list[tuple[str, str]] = []

    async def mark_status(run_id: str, status: str, metadata: dict[str, object]) -> None:
        statuses.append((run_id, status))

    queue = BackgroundRunQueue(status_writer=mark_status)

    async def work(token) -> str:
        assert not token.cancelled
        return "ok"

    handle = queue.enqueue("team-run-1", "team", lambda token: work(token))

    assert handle.run_id == "team-run-1"
    assert queue.get_status("team-run-1")["status"] in {"queued", "running"}
    await handle.task
    assert queue.get_status("team-run-1")["status"] == "completed"
    assert statuses[-1] == ("team-run-1", "completed")


@pytest.mark.asyncio
async def test_background_queue_cancellation_stops_future_work() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    queue = BackgroundRunQueue()

    async def work(token) -> str:
        started.set()
        await release.wait()
        token.raise_if_cancelled()
        return "late"

    handle = queue.enqueue("workflow-1", "workflow", lambda token: work(token))
    await started.wait()

    assert queue.cancel("workflow-1", reason="user requested") is True
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await handle.task
    assert queue.get_status("workflow-1")["status"] == "cancelled"
    assert queue.get_status("workflow-1")["reason"] == "user requested"


@pytest.mark.asyncio
async def test_background_queue_persists_failure() -> None:
    queue = BackgroundRunQueue()

    async def work(token) -> str:
        raise RuntimeError("boom")

    handle = queue.enqueue("team-run-fail", "team", lambda token: work(token))

    with pytest.raises(RuntimeError, match="boom"):
        await handle.task
    status = queue.get_status("team-run-fail")
    assert status["status"] == "failed"
    assert status["error_type"] == "RuntimeError"
    assert status["error_message"] == "boom"


def test_background_queue_marks_orphans_interrupted() -> None:
    interrupted: list[str] = []

    def orphan_provider() -> list[dict[str, object]]:
        return [{"id": "team-run-old", "kind": "team"}]

    async def mark_status(run_id: str, status: str, metadata: dict[str, object]) -> None:
        interrupted.append(run_id)

    queue = BackgroundRunQueue(
        status_writer=mark_status,
        orphan_provider=orphan_provider,
    )

    assert queue.mark_orphans_interrupted() == 1
    assert interrupted == ["team-run-old"]
