"""run_metrics — per-run aggregated telemetry counters.

S8 introduces a ``run_metrics`` table that complements OpenTelemetry
spans. Spans capture *what happened*; ``run_metrics`` captures the
quantitative summary (turn count, tool count, prompt chars, latency
breakdown, error counters) used by the eval suites and replay
harness. One row per run. Cheap to query, cheap to aggregate.

Revision ID: 0007_run_metrics
Revises: 0006_subagent_runs
Create Date: 2026-04-28
"""

from __future__ import annotations

from alembic import op

revision = "0007_run_metrics"
down_revision = "0006_subagent_runs"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS run_metrics (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT 'default',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms REAL NOT NULL DEFAULT 0.0,
    turn_count INTEGER NOT NULL DEFAULT 0,
    tool_count INTEGER NOT NULL DEFAULT 0,
    tool_error_count INTEGER NOT NULL DEFAULT 0,
    prompt_chars INTEGER NOT NULL DEFAULT 0,
    output_chars INTEGER NOT NULL DEFAULT 0,
    loop_signals INTEGER NOT NULL DEFAULT 0,
    drift_signals INTEGER NOT NULL DEFAULT 0,
    citations_count INTEGER NOT NULL DEFAULT 0,
    terminal_reason TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(session_id, run_id)
);

CREATE INDEX IF NOT EXISTS idx_run_metrics_session
    ON run_metrics(session_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_run_metrics_agent
    ON run_metrics(agent_id, started_at DESC);
"""


DROP_SQL = """
DROP INDEX IF EXISTS idx_run_metrics_agent;
DROP INDEX IF EXISTS idx_run_metrics_session;
DROP TABLE IF EXISTS run_metrics;
"""


def upgrade() -> None:
    for statement in SCHEMA_SQL.split(";"):
        sql = statement.strip()
        if sql:
            op.execute(sql)


def downgrade() -> None:
    for statement in DROP_SQL.split(";"):
        sql = statement.strip()
        if sql:
            op.execute(sql)
