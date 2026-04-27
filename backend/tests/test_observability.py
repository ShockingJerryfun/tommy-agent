"""Tests for the S8 observability + eval surface."""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest

from app.agent_framework.observability import (
    MaintenanceJob,
    MaintenanceScheduler,
    RunMetricsRecorder,
    get_tracer,
    replay_session,
    span,
)
from app.agent_framework.observability.eval_suites import (
    eval_compaction,
    eval_hallucination,
    eval_loop,
    eval_recall,
    eval_tool_safety,
)
from app.agent_framework.store import PostgresAgentStore


def _store() -> PostgresAgentStore:
    store = PostgresAgentStore()
    store.reset_for_tests()
    return store


def _new_session(store: PostgresAgentStore) -> str:
    sid = f"sess-{uuid.uuid4().hex[:8]}"
    store.create_session(session_id=sid, agent_id="default", title="t")
    return sid


# ---------------------------------------------------------------------- tracer


def test_tracer_returns_a_tracer_object() -> None:
    tracer = get_tracer()
    assert tracer is not None


def test_span_context_manager_is_safe_without_sdk() -> None:
    with span("tommy.test", attributes={"x": 1, "obj": object()}) as current:
        # We don't assert anything about ``current`` because the API
        # may return either a real span or a no-op shim depending on
        # whether an SDK is configured. The contract is that this
        # context manager never raises.
        if current is not None and hasattr(current, "set_attribute"):
            current.set_attribute("y", "z")


# --------------------------------------------------------------------- metrics


def test_run_metrics_recorder_round_trips() -> None:
    store = _store()
    sid = _new_session(store)
    rid = "run-1"
    recorder = RunMetricsRecorder(store, session_id=sid, run_id=rid)
    recorder.start()
    recorder.tick_turn()
    recorder.tick_turn()
    recorder.record_tool(error=False)
    recorder.record_tool(error=True)
    recorder.record_prompt_chars(1234)
    recorder.record_loop_signal()
    recorder.record_drift_signal()
    recorder.record_citations(2)
    recorder.update_metadata({"plan_steps": 3})
    row = recorder.finalize(terminal_reason="completed", output_chars=512)

    assert row["session_id"] == sid
    assert row["run_id"] == rid
    assert row["turn_count"] == 2
    assert row["tool_count"] == 2
    assert row["tool_error_count"] == 1
    assert row["prompt_chars"] == 1234
    assert row["output_chars"] == 512
    assert row["loop_signals"] == 1
    assert row["drift_signals"] == 1
    assert row["citations_count"] == 2
    assert row["terminal_reason"] == "completed"
    assert row["metadata"]["plan_steps"] == 3
    assert row["finished_at"]
    assert row["duration_ms"] >= 0.0


def test_run_metrics_upsert_replaces_previous_row() -> None:
    store = _store()
    sid = _new_session(store)
    rid = "run-2"
    r1 = RunMetricsRecorder(store, session_id=sid, run_id=rid)
    r1.start()
    r1.tick_turn()
    r1.finalize(terminal_reason="ok")
    r2 = RunMetricsRecorder(store, session_id=sid, run_id=rid)
    r2.start()
    r2.tick_turn(3)
    r2.finalize(terminal_reason="completed")

    rows = store.run_metrics.list_for_session(sid)
    assert len(rows) == 1
    assert rows[0]["turn_count"] == 3
    assert rows[0]["terminal_reason"] == "completed"


# ----------------------------------------------------------------------- replay


def test_replay_session_uses_persisted_user_inputs() -> None:
    store = _store()
    sid = _new_session(store)
    store.append_message(sid, role="user", content="Hello?")
    store.append_message(sid, role="assistant", content="Hi.")
    store.append_message(sid, role="user", content="What's 2+2?")

    seen: list[str] = []

    def runner(user_input: str, _ctx):
        seen.append(user_input)
        return {
            "final_response": (
                f"answer: {user_input} https://example.com/{len(seen)}"
            ),
            "intermediate_steps": [{"node": "action", "tool": "web_search"}],
        }

    report = replay_session(store, session_id=sid, runner=runner)
    assert report.total_inputs == 2
    assert report.errors == 0
    assert report.total_citations == 2
    assert report.total_tools == 2
    assert seen == ["Hello?", "What's 2+2?"]


def test_replay_runner_failure_is_isolated() -> None:
    store = _store()
    sid = _new_session(store)
    store.append_message(sid, role="user", content="x")

    def boom(_user_input, _ctx):
        raise RuntimeError("model broken")

    report = replay_session(store, session_id=sid, runner=boom)
    assert report.errors == 1
    assert "model broken" in (report.outcomes[0].error or "")


# ----------------------------------------------------------------- eval suites


def test_eval_tool_safety_passes() -> None:
    report = eval_tool_safety(None)
    assert report.passed, [
        (c.name, c.detail) for c in report.checks if not c.passed
    ]


def test_eval_loop_passes() -> None:
    report = eval_loop(None)
    assert report.passed


def test_eval_hallucination_passes() -> None:
    report = eval_hallucination(None)
    assert report.passed


def test_eval_recall_passes() -> None:
    store = _store()
    report = eval_recall(store)
    assert report.passed, [c.detail for c in report.checks if not c.passed]


def test_eval_compaction_passes() -> None:
    store = _store()
    report = eval_compaction(store)
    assert report.passed, [c.detail for c in report.checks if not c.passed]


# -------------------------------------------------------------- maintenance


def test_maintenance_scheduler_runs_jobs_and_cancels_cleanly() -> None:
    async def main() -> dict[str, str]:
        ticks: dict[str, int] = {"a": 0, "b": 0}

        async def job_a() -> None:
            ticks["a"] += 1

        def job_b() -> None:
            ticks["b"] += 1

        scheduler = MaintenanceScheduler(
            jobs=[
                MaintenanceJob("a", interval_seconds=10.0, body=job_a),
                MaintenanceJob("b", interval_seconds=10.0, body=job_b),
            ]
        )
        await scheduler.start()
        # Each job runs once immediately on start. Give the loop a moment.
        await asyncio.sleep(0.05)
        await scheduler.stop()
        return scheduler.last_outcomes

    outcomes = asyncio.run(main())
    assert outcomes.get("a") == "ok"
    assert outcomes.get("b") == "ok"


def test_maintenance_scheduler_isolates_failures() -> None:
    async def main() -> dict[str, str]:
        def boom() -> None:
            raise RuntimeError("nope")

        scheduler = MaintenanceScheduler(
            jobs=[MaintenanceJob("boom", interval_seconds=10.0, body=boom)]
        )
        await scheduler.run_once("boom")
        return scheduler.last_outcomes

    outcomes = asyncio.run(main())
    assert outcomes["boom"].startswith("error: ")


# Skip flaky time-sensitive timing checks under heavy CI load.
@pytest.mark.parametrize("_iter", range(1))
def test_run_metrics_records_positive_duration(_iter: int) -> None:
    store = _store()
    sid = _new_session(store)
    recorder = RunMetricsRecorder(store, session_id=sid, run_id=f"r-{_iter}")
    recorder.start()
    time.sleep(0.005)
    row = recorder.finalize(terminal_reason="ok")
    assert row["duration_ms"] >= 1.0
