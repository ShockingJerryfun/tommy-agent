from __future__ import annotations

KNOWLEDGE_DDL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('proposed', 'active', 'rejected')),
    source_session_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

ALTER TABLE memories ADD COLUMN IF NOT EXISTS embedding vector(1536);
ALTER TABLE memories ADD COLUMN IF NOT EXISTS embedding_model TEXT NOT NULL DEFAULT '';
ALTER TABLE memories
    ADD COLUMN IF NOT EXISTS fts tsvector
    GENERATED ALWAYS AS (to_tsvector('simple', coalesce(content, ''))) STORED;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS importance REAL NOT NULL DEFAULT 0.5;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS last_used_at TEXT;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS use_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS decay_score REAL NOT NULL DEFAULT 0.0;

CREATE INDEX IF NOT EXISTS idx_memories_agent_status_updated
    ON memories(agent_id, status, updated_at);

CREATE INDEX IF NOT EXISTS idx_memories_content_trgm
    ON memories USING GIN (content gin_trgm_ops);

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

CREATE TABLE IF NOT EXISTS context_pacts (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    pact_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compaction_runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    run_id TEXT,
    summary TEXT NOT NULL,
    message_count INTEGER NOT NULL,
    kept_messages INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_compaction_runs_session_created
    ON compaction_runs(session_id, created_at);
"""
