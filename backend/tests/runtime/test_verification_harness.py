from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.agent_framework.runtime import RunCreatePayload, RunManager
from app.agent_framework.runtime.verification import (
    TaskVerifier,
    VerificationAttempt,
    VerificationCommand,
    VerificationSummary,
)
from app.agent_framework.storage import PostgresAgentStore
from tests.runtime.test_run_manager_mock import FakeChunk, MockStreamGraph


@dataclass
class FakeVerifier:
    summary: VerificationSummary
    calls: int = 0
    last_max_attempts: int | None = None

    def should_verify(self, payload: RunCreatePayload, *, changed_files_seen: bool = False) -> bool:
        text = payload.message.casefold()
        return changed_files_seen or "code" in text or "test" in text or "modify" in text

    async def verify(
        self,
        *,
        payload: RunCreatePayload,
        run_id: str,
        max_attempts: int,
    ) -> VerificationSummary:
        self.calls += 1
        self.last_max_attempts = max_attempts
        return self.summary


def _summary(status: str, *, attempts: int = 1) -> VerificationSummary:
    return VerificationSummary(
        status=status,
        attempts=[
            VerificationAttempt(
                attempt=index + 1,
                command="python -m pytest -q",
                status=status,
                exit_code=0 if status == "passed" else 1,
                output="ok" if status == "passed" else "failed assertion",
                reason="",
            )
            for index in range(attempts)
        ],
        max_attempts=attempts,
        summary="验证通过" if status == "passed" else "验证失败: python -m pytest -q",
    )


async def _run_with_verifier(
    message: str,
    verifier: FakeVerifier,
    *,
    max_attempts: int = 2,
) -> tuple[PostgresAgentStore, str, str]:
    store = PostgresAgentStore()
    store.reset_for_tests()
    graph = MockStreamGraph([("messages", (FakeChunk("answer"), {"langgraph_node": "agent"}))])

    async def factory() -> Any:
        return graph

    manager = RunManager(
        store=store,
        graph_factory=factory,
        verifier=verifier,
        max_verification_attempts=max_attempts,
    )
    session_id = store.create_session(agent_id="default")
    run = await manager.create_and_start_run(
        RunCreatePayload(session_id=session_id, message=message, agent_id="default"),
    )
    run_id = str(run["id"])
    async for event in manager.stream_run_events(run_id):
        if event.type == "done":
            break
    return store, session_id, run_id


@pytest.mark.asyncio
async def test_plain_chat_does_not_trigger_verifier() -> None:
    verifier = FakeVerifier(_summary("passed"))
    store, session_id, _ = await _run_with_verifier("Hello, how are you?", verifier)

    assert verifier.calls == 0
    assert [
        event["type"]
        for event in store.list_run_events(session_id)
        if event["type"].startswith("verification")
    ] == []


@pytest.mark.asyncio
async def test_coding_task_triggers_verifier_and_persists_success_events() -> None:
    verifier = FakeVerifier(_summary("passed"))
    store, session_id, _ = await _run_with_verifier("Please modify code and run tests", verifier)

    assert verifier.calls == 1
    events = store.list_run_events(session_id)
    verification_events = [event for event in events if event["type"].startswith("verification")]
    assert [event["type"] for event in verification_events] == [
        "verification_start",
        "verification_end",
    ]
    assert verification_events[-1]["payload"]["status"] == "passed"
    assistant = [m for m in store.list_messages(session_id) if m.role == "assistant"][-1]
    assert "验证摘要" in assistant.content
    assert "验证通过" in assistant.content


@pytest.mark.asyncio
async def test_verifier_failure_is_summarised() -> None:
    verifier = FakeVerifier(_summary("failed"))
    store, session_id, _ = await _run_with_verifier("Modify code and test it", verifier)

    verification_end = [
        event for event in store.list_run_events(session_id) if event["type"] == "verification_end"
    ][-1]
    assert verification_end["payload"]["status"] == "failed"
    assistant = [m for m in store.list_messages(session_id) if m.role == "assistant"][-1]
    assert "验证失败" in assistant.content
    assert "python -m pytest -q" in assistant.content


@pytest.mark.asyncio
async def test_verifier_respects_max_attempts() -> None:
    verifier = FakeVerifier(_summary("failed", attempts=2))
    store, session_id, _ = await _run_with_verifier(
        "Modify code and run tests",
        verifier,
        max_attempts=2,
    )

    assert verifier.calls == 2
    assert verifier.last_max_attempts == 1
    verification_end = [
        event for event in store.list_run_events(session_id) if event["type"] == "verification_end"
    ][-1]
    assert verification_end["payload"]["max_attempts"] == 2
    assert len(verification_end["payload"]["attempts"]) == 2


@pytest.mark.asyncio
async def test_task_verifier_stops_after_max_attempts(tmp_path) -> None:
    (tmp_path / "tests").mkdir()
    calls: list[VerificationCommand] = []

    def runner(command: VerificationCommand, attempt: int) -> VerificationAttempt:
        calls.append(command)
        return VerificationAttempt(
            attempt=attempt,
            command=command.display,
            status="failed",
            exit_code=1,
            output="test failed",
        )

    verifier = TaskVerifier(command_runner=runner)
    summary = await verifier.verify(
        payload=RunCreatePayload(
            session_id="s",
            message="Modify code and run tests",
            metadata={"frontend_settings": {"workingDirectory": str(tmp_path)}},
        ),
        run_id="run-1",
        max_attempts=2,
    )

    assert summary.status == "failed"
    assert [attempt.attempt for attempt in summary.attempts] == [1, 2]
    assert len(calls) == 2
    assert all(isinstance(call.command, tuple) for call in calls)
