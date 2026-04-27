"""prompt_snapshots + memory_injections

Adds the audit tables that back ContextBuilder v2:

- ``prompt_snapshots`` — one row per assembled prompt (per turn). Captures
  the section budget accounting, total characters, the deterministic section
  list, and a ``content_sha256`` so identical prompts can be deduplicated and
  replayed.
- ``memory_injections`` — one row per memory item that was injected into a
  prompt. Links to the snapshot, the run, and the source memory so we can
  audit which memories influenced which turns. ``score`` and ``rank`` are
  populated by the S2 hybrid retriever; in S1 we record the items returned
  by the existing search and leave ``score`` NULL.

Revision ID: 0002_context_v2
Revises: 0001_baseline
Create Date: 2026-04-27
"""

from __future__ import annotations

from alembic import op

revision = "0002_context_v2"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS prompt_snapshots (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    run_id TEXT,
    agent_id TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    total_chars INTEGER NOT NULL,
    section_count INTEGER NOT NULL,
    truncated_count INTEGER NOT NULL DEFAULT 0,
    dropped_count INTEGER NOT NULL DEFAULT 0,
    content_sha256 TEXT NOT NULL,
    sections_json TEXT NOT NULL DEFAULT '[]',
    budget_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prompt_snapshots_session_created
    ON prompt_snapshots(session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_prompt_snapshots_run_created
    ON prompt_snapshots(run_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_prompt_snapshots_hash
    ON prompt_snapshots(content_sha256);

CREATE TABLE IF NOT EXISTS memory_injections (
    id TEXT PRIMARY KEY,
    snapshot_id TEXT REFERENCES prompt_snapshots(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    run_id TEXT,
    agent_id TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    query TEXT NOT NULL DEFAULT '',
    rank INTEGER NOT NULL DEFAULT 0,
    score DOUBLE PRECISION,
    char_count INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_injections_session_created
    ON memory_injections(session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_injections_run_rank
    ON memory_injections(run_id, rank);

CREATE INDEX IF NOT EXISTS idx_memory_injections_memory
    ON memory_injections(memory_id, created_at DESC);
"""


DROP_SQL = """
DROP TABLE IF EXISTS memory_injections;
DROP TABLE IF EXISTS prompt_snapshots;
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
