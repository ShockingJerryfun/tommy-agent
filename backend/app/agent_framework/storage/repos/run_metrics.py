"""Per-run aggregate metrics persistence."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ._base import Connector, dumps, loads, utc_now


class RunMetricsRepo:
    SELECT_COLUMNS = (
        "id, session_id, run_id, agent_id, started_at, finished_at, "
        "duration_ms, model, prompt_tokens, completion_tokens, total_tokens, "
        "reasoning_tokens, finish_reason, status, error_count, cancelled, interrupted, "
        "turn_count, tool_count, tool_error_count, "
        "prompt_chars, output_chars, loop_signals, drift_signals, "
        "citations_count, terminal_reason, metadata_json"
    )

    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def upsert(
        self,
        *,
        session_id: str,
        run_id: str,
        agent_id: str = "default",
        started_at: str | None = None,
        finished_at: str | None = None,
        duration_ms: float = 0.0,
        model: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        finish_reason: str | None = None,
        status: str | None = None,
        error_count: int = 0,
        cancelled: bool = False,
        interrupted: bool = False,
        turn_count: int = 0,
        tool_count: int = 0,
        tool_error_count: int = 0,
        prompt_chars: int = 0,
        output_chars: int = 0,
        loop_signals: int = 0,
        drift_signals: int = 0,
        citations_count: int = 0,
        terminal_reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metric_id = f"rm-{uuid4().hex}"
        started = started_at or utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO run_metrics(
                    id, session_id, run_id, agent_id, started_at, finished_at,
                    duration_ms, model, prompt_tokens, completion_tokens, total_tokens,
                    reasoning_tokens, finish_reason, status, error_count, cancelled, interrupted,
                    turn_count, tool_count, tool_error_count,
                    prompt_chars, output_chars, loop_signals, drift_signals,
                    citations_count, terminal_reason, metadata_json
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(session_id, run_id) DO UPDATE SET
                    agent_id = excluded.agent_id,
                    finished_at = excluded.finished_at,
                    duration_ms = excluded.duration_ms,
                    model = excluded.model,
                    prompt_tokens = excluded.prompt_tokens,
                    completion_tokens = excluded.completion_tokens,
                    total_tokens = excluded.total_tokens,
                    reasoning_tokens = excluded.reasoning_tokens,
                    finish_reason = excluded.finish_reason,
                    status = excluded.status,
                    error_count = excluded.error_count,
                    cancelled = excluded.cancelled,
                    interrupted = excluded.interrupted,
                    turn_count = excluded.turn_count,
                    tool_count = excluded.tool_count,
                    tool_error_count = excluded.tool_error_count,
                    prompt_chars = excluded.prompt_chars,
                    output_chars = excluded.output_chars,
                    loop_signals = excluded.loop_signals,
                    drift_signals = excluded.drift_signals,
                    citations_count = excluded.citations_count,
                    terminal_reason = excluded.terminal_reason,
                    metadata_json = excluded.metadata_json
                """,
                (
                    metric_id,
                    session_id,
                    run_id,
                    agent_id,
                    started,
                    finished_at,
                    float(duration_ms),
                    model,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    reasoning_tokens,
                    finish_reason,
                    status,
                    int(error_count),
                    bool(cancelled),
                    bool(interrupted),
                    int(turn_count),
                    int(tool_count),
                    int(tool_error_count),
                    int(prompt_chars),
                    int(output_chars),
                    int(loop_signals),
                    int(drift_signals),
                    int(citations_count),
                    terminal_reason,
                    dumps(metadata),
                ),
            )
        return self.get(session_id=session_id, run_id=run_id) or {}

    def get(self, *, session_id: str, run_id: str) -> dict[str, Any] | None:
        with self._connector.connect() as conn:
            row = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM run_metrics
                WHERE session_id = ? AND run_id = ?
                """,
                (session_id, run_id),
            ).fetchone()
        return _hydrate(row) if row is not None else None

    def list_for_session(self, session_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM run_metrics
                WHERE session_id = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (session_id, int(limit)),
            ).fetchall()
        return [_hydrate(row) for row in rows]

    def list_for_agent(self, agent_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM run_metrics
                WHERE agent_id = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (agent_id, int(limit)),
            ).fetchall()
        return [_hydrate(row) for row in rows]


def _hydrate(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "run_id": row["run_id"],
        "agent_id": row["agent_id"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "duration_ms": float(row["duration_ms"]),
        "model": row["model"],
        "prompt_tokens": row["prompt_tokens"],
        "completion_tokens": row["completion_tokens"],
        "total_tokens": row["total_tokens"],
        "reasoning_tokens": row["reasoning_tokens"],
        "finish_reason": row["finish_reason"],
        "status": row["status"],
        "error_count": int(row["error_count"] or 0),
        "cancelled": bool(row["cancelled"]),
        "interrupted": bool(row["interrupted"]),
        "turn_count": row["turn_count"],
        "tool_count": row["tool_count"],
        "tool_error_count": row["tool_error_count"],
        "prompt_chars": row["prompt_chars"],
        "output_chars": row["output_chars"],
        "loop_signals": row["loop_signals"],
        "drift_signals": row["drift_signals"],
        "citations_count": row["citations_count"],
        "terminal_reason": row["terminal_reason"],
        "metadata": loads(row["metadata_json"]),
    }
