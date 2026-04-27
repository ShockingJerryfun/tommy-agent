"""subagent_runs — parent/child run linkage and best-of-N tracking

The S6 stage introduces real subagents. We track each delegation in a
dedicated table that captures the parent → child relationship, the
role-bound tool scope, the final response, and the deterministic score
the best-of-N merger uses to pick a winner.

Sessions and runs are intentionally left untouched: the child session is
a regular session row; this table records the cross-link plus the
subagent-specific metadata.

Columns:

- ``id`` — unique subagent run id (``sub-<uuid>``)
- ``parent_session_id`` / ``parent_run_id`` — caller context
- ``child_session_id`` / ``child_run_id`` — the spawned session/run
- ``role`` — bound role string (``researcher`` / ``analyst`` / ``writer``)
- ``task`` — the task prompt fed to the subagent
- ``status`` — ``queued`` / ``running`` / ``completed`` / ``failed`` /
  ``stopped``
- ``score`` — deterministic score (0..1); higher is better. Used by the
  best-of-N merger.
- ``final_response`` — final assistant message returned by the subagent
- ``metadata_json`` — bag for permission scope, citations summary, etc.

Revision ID: 0006_subagent_runs
Revises: 0005_skills_forge
Create Date: 2026-04-27
"""

from __future__ import annotations

from alembic import op

revision = "0006_subagent_runs"
down_revision = "0005_skills_forge"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS subagent_runs (
    id TEXT PRIMARY KEY,
    parent_session_id TEXT NOT NULL,
    parent_run_id TEXT NOT NULL,
    child_session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    child_run_id TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL,
    task TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK(status IN ('queued', 'running', 'completed', 'failed', 'stopped')),
    score REAL NOT NULL DEFAULT 0.0,
    attempt_index INTEGER NOT NULL DEFAULT 0,
    final_response TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_subagent_runs_parent_session
    ON subagent_runs(parent_session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_subagent_runs_parent_run
    ON subagent_runs(parent_session_id, parent_run_id, attempt_index);

CREATE INDEX IF NOT EXISTS idx_subagent_runs_child
    ON subagent_runs(child_session_id);
"""


DROP_SQL = """
DROP INDEX IF EXISTS idx_subagent_runs_child;
DROP INDEX IF EXISTS idx_subagent_runs_parent_run;
DROP INDEX IF EXISTS idx_subagent_runs_parent_session;
DROP TABLE IF EXISTS subagent_runs;
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
