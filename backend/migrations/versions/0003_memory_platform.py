"""memory platform — pgvector + FTS + lifecycle columns + consolidation log

Adds the columns, indexes, and audit table that back the S2 memory
platform:

- ``CREATE EXTENSION vector`` so pgvector is available for HNSW indexes.
- ``memories.embedding``: ``vector(1536)`` column (matches OpenAI's
  ``text-embedding-3-*`` family and the EchoEmbedder used in tests).
- ``memories.embedding_model``: tracks which model produced an embedding so
  re-embedding can target a single model without rewriting the whole table.
- ``memories.fts``: stored generated tsvector column over ``content`` with
  a GIN index for sub-millisecond keyword recall.
- Lifecycle columns (``importance``, ``last_used_at``, ``use_count``,
  ``decay_score``) consumed by the Forgetter pipeline.
- ``memory_consolidation_runs``: append-only audit log of every reflector,
  consolidator, forgetter, and on_pre_compact flush invocation.

The migration is idempotent (``IF NOT EXISTS`` everywhere) so it can be
applied to a freshly provisioned database or to one already brought up
with the legacy ``ensure_schema`` bootstrap.

Revision ID: 0003_memory_platform
Revises: 0002_context_v2
Create Date: 2026-04-27
"""

from __future__ import annotations

from alembic import op

revision = "0003_memory_platform"
down_revision = "0002_context_v2"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE memories ADD COLUMN IF NOT EXISTS embedding vector(1536);

ALTER TABLE memories ADD COLUMN IF NOT EXISTS embedding_model TEXT NOT NULL DEFAULT '';

ALTER TABLE memories
    ADD COLUMN IF NOT EXISTS fts tsvector
    GENERATED ALWAYS AS (to_tsvector('simple', coalesce(content, ''))) STORED;

ALTER TABLE memories ADD COLUMN IF NOT EXISTS importance REAL NOT NULL DEFAULT 0.5;

ALTER TABLE memories ADD COLUMN IF NOT EXISTS last_used_at TEXT;

ALTER TABLE memories ADD COLUMN IF NOT EXISTS use_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE memories ADD COLUMN IF NOT EXISTS decay_score REAL NOT NULL DEFAULT 0.0;

CREATE INDEX IF NOT EXISTS idx_memories_fts
    ON memories USING GIN (fts);

CREATE INDEX IF NOT EXISTS idx_memories_embedding_hnsw
    ON memories USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_memories_agent_use
    ON memories(agent_id, status, use_count, last_used_at);

CREATE TABLE IF NOT EXISTS memory_consolidation_runs (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    session_id TEXT,
    run_id TEXT,
    kind TEXT NOT NULL CHECK(kind IN ('reflect','consolidate','forget','flush')),
    inputs_count INTEGER NOT NULL DEFAULT 0,
    outputs_count INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_consolidation_runs_agent_kind
    ON memory_consolidation_runs(agent_id, kind, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_consolidation_runs_session
    ON memory_consolidation_runs(session_id, created_at DESC);
"""


DROP_SQL = """
DROP TABLE IF EXISTS memory_consolidation_runs;
DROP INDEX IF EXISTS idx_memories_agent_use;
DROP INDEX IF EXISTS idx_memories_embedding_hnsw;
DROP INDEX IF EXISTS idx_memories_fts;
ALTER TABLE memories DROP COLUMN IF EXISTS decay_score;
ALTER TABLE memories DROP COLUMN IF EXISTS use_count;
ALTER TABLE memories DROP COLUMN IF EXISTS last_used_at;
ALTER TABLE memories DROP COLUMN IF EXISTS importance;
ALTER TABLE memories DROP COLUMN IF EXISTS fts;
ALTER TABLE memories DROP COLUMN IF EXISTS embedding_model;
ALTER TABLE memories DROP COLUMN IF EXISTS embedding;
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
