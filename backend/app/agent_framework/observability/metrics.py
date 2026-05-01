"""RunMetricsRecorder — typed accumulator that flushes once per run.

Usage:

    recorder = RunMetricsRecorder(store, session_id=sid, run_id=rid)
    recorder.start()
    recorder.tick_turn()
    recorder.record_tool(error=False)
    recorder.record_prompt_chars(1234)
    recorder.finalize(terminal_reason="completed", output_chars=400)

All public methods are pure data manipulation except ``finalize``,
which writes a single ``run_metrics`` row.
"""

from __future__ import annotations

import time
from typing import Any

from ..storage import PostgresAgentStore


class RunMetricsRecorder:
    def __init__(
        self,
        store: PostgresAgentStore,
        *,
        session_id: str,
        run_id: str,
        agent_id: str = "default",
    ) -> None:
        self.store = store
        self.session_id = session_id
        self.run_id = run_id
        self.agent_id = agent_id
        self._started_at: str | None = None
        self._start_perf: float | None = None
        self.turn_count = 0
        self.tool_count = 0
        self.tool_error_count = 0
        self.prompt_chars = 0
        self.output_chars = 0
        self.loop_signals = 0
        self.drift_signals = 0
        self.citations_count = 0
        self.model: str | None = None
        self.prompt_tokens: int | None = None
        self.completion_tokens: int | None = None
        self.total_tokens: int | None = None
        self.reasoning_tokens: int | None = None
        self.finish_reason: str | None = None
        self.error_count = 0
        self.metadata: dict[str, Any] = {}
        self.finalized = False

    # ------------------------------------------------------------- mutators

    def start(self) -> None:
        if self._started_at is not None:
            return
        from datetime import UTC, datetime

        self._started_at = datetime.now(UTC).isoformat()
        self._start_perf = time.perf_counter()

    def tick_turn(self, n: int = 1) -> None:
        self.turn_count += n

    def record_tool(self, *, error: bool = False, n: int = 1) -> None:
        self.tool_count += n
        if error:
            self.tool_error_count += n

    def record_prompt_chars(self, chars: int) -> None:
        self.prompt_chars += int(chars)

    def record_output_chars(self, chars: int) -> None:
        self.output_chars += int(chars)

    def record_loop_signal(self, n: int = 1) -> None:
        self.loop_signals += n

    def record_drift_signal(self, n: int = 1) -> None:
        self.drift_signals += n

    def record_citations(self, n: int) -> None:
        self.citations_count += int(n)

    def record_token_usage(
        self,
        *,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        model: str | None = None,
        finish_reason: str | None = None,
    ) -> None:
        self.prompt_tokens = _merge_optional_int(self.prompt_tokens, prompt_tokens)
        self.completion_tokens = _merge_optional_int(self.completion_tokens, completion_tokens)
        self.total_tokens = _merge_optional_int(self.total_tokens, total_tokens)
        self.reasoning_tokens = _merge_optional_int(self.reasoning_tokens, reasoning_tokens)
        self.model = model or self.model
        self.finish_reason = finish_reason or self.finish_reason

    def record_error(self, n: int = 1) -> None:
        self.error_count += int(n)

    def update_metadata(self, patch: dict[str, Any]) -> None:
        self.metadata.update(patch or {})

    # ------------------------------------------------------------- finalize

    def finalize(
        self,
        *,
        terminal_reason: str = "",
        status: str | None = None,
        output_chars: int | None = None,
    ) -> dict[str, Any]:
        from datetime import UTC, datetime

        if self._started_at is None:
            self.start()
        finished_at = datetime.now(UTC).isoformat()
        duration_ms = (
            (time.perf_counter() - self._start_perf) * 1000.0
            if self._start_perf is not None
            else 0.0
        )
        if output_chars is not None:
            self.output_chars = int(output_chars)
        row = self.store.run_metrics.upsert(
            session_id=self.session_id,
            run_id=self.run_id,
            agent_id=self.agent_id,
            started_at=self._started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            model=self.model,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.total_tokens,
            reasoning_tokens=self.reasoning_tokens,
            finish_reason=self.finish_reason,
            status=status or terminal_reason,
            error_count=self.error_count,
            cancelled=(status or terminal_reason) == "cancelled",
            interrupted=(status or terminal_reason) == "interrupted",
            turn_count=self.turn_count,
            tool_count=self.tool_count,
            tool_error_count=self.tool_error_count,
            prompt_chars=self.prompt_chars,
            output_chars=self.output_chars,
            loop_signals=self.loop_signals,
            drift_signals=self.drift_signals,
            citations_count=self.citations_count,
            terminal_reason=terminal_reason,
            metadata=self.metadata,
        )
        self.finalized = True
        return row


def _merge_optional_int(current: int | None, incoming: int | None) -> int | None:
    if incoming is None:
        return current
    if current is None:
        return int(incoming)
    return current + int(incoming)
