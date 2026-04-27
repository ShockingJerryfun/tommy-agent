"""Schema bootstrap.

The canonical schema lives in ``migrations/versions/0001_baseline_schema.py``.
This module exists so the runtime can keep the legacy ``ensure_schema``
behavior (idempotent ``CREATE TABLE IF NOT EXISTS``) without taking a hard
dependency on Alembic at import time.
"""

from __future__ import annotations

from ._base import Connector, is_test_database_dsn

SCHEMA_DDL = """
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    title TEXT NOT NULL,
    preview TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_agent_deleted_updated
    ON sessions(agent_id, deleted_at, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    position INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session_position
    ON messages(session_id, position);

CREATE INDEX IF NOT EXISTS idx_messages_session_role_position
    ON messages(session_id, role, position);

CREATE TABLE IF NOT EXISTS run_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    type TEXT NOT NULL,
    label TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    sequence INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_run_events_session_sequence
    ON run_events(session_id, sequence);

CREATE INDEX IF NOT EXISTS idx_run_events_run_sequence
    ON run_events(run_id, sequence);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(
        status IN ('queued','running','completed','cancelled','interrupted','error')
    ),
    input TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    assistant_message_id TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    error TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_runs_session_updated
    ON runs(session_id, updated_at);

CREATE INDEX IF NOT EXISTS idx_runs_status_updated
    ON runs(status, updated_at);

CREATE INDEX IF NOT EXISTS idx_runs_active_session_updated
    ON runs(session_id, updated_at DESC)
    WHERE status IN ('queued', 'running') AND finished_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_runs_active_updated
    ON runs(updated_at DESC)
    WHERE status IN ('queued', 'running') AND finished_at IS NULL;

CREATE TABLE IF NOT EXISTS run_controls (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK(
        status IN ('running', 'stopping', 'stopped', 'completed', 'error')
    ),
    stop_reason TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    stop_requested_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_run_controls_session_status
    ON run_controls(session_id, status, updated_at);

CREATE TABLE IF NOT EXISTS tool_calls (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    args_json TEXT NOT NULL DEFAULT '{}',
    result TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_session_created
    ON tool_calls(session_id, created_at);

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

CREATE TABLE IF NOT EXISTS tool_artifacts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    run_id TEXT,
    tool_call_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'tool_output',
    mime TEXT NOT NULL DEFAULT 'text/plain',
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    body TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_artifacts_session
    ON tool_artifacts(session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_tool_artifacts_tool_call
    ON tool_artifacts(tool_call_id);

CREATE INDEX IF NOT EXISTS idx_tool_artifacts_sha256
    ON tool_artifacts(sha256);

CREATE TABLE IF NOT EXISTS skill_proposals (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    name TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('create', 'update')),
    rationale TEXT NOT NULL,
    content TEXT NOT NULL,
    risks_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK(status IN ('proposed', 'applied', 'rejected')),
    version_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    applied_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_skill_proposals_agent_status
    ON skill_proposals(agent_id, status, updated_at);

CREATE TABLE IF NOT EXISTS skill_versions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    name TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    content TEXT NOT NULL,
    previous_content TEXT NOT NULL DEFAULT '',
    proposal_id TEXT REFERENCES skill_proposals(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_skill_versions_agent_path
    ON skill_versions(agent_id, relative_path, created_at);

CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    name TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    signature TEXT NOT NULL DEFAULT '',
    signature_embedding vector(1536),
    embedding_model TEXT NOT NULL DEFAULT '',
    tool_chain_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'shadow'
        CHECK(status IN ('shadow', 'active', 'retired')),
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    invocation_count INTEGER NOT NULL DEFAULT 0,
    avg_latency_ms REAL NOT NULL DEFAULT 0.0,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    proposal_id TEXT REFERENCES skill_proposals(id) ON DELETE SET NULL,
    version_id TEXT REFERENCES skill_versions(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_used_at TEXT,
    UNIQUE(agent_id, relative_path)
);

CREATE INDEX IF NOT EXISTS idx_skills_agent_status_updated
    ON skills(agent_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_skills_signature_hnsw
    ON skills USING hnsw (signature_embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS skill_forge_runs (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('mine', 'validate', 'promote', 'retire')),
    inputs_count INTEGER NOT NULL DEFAULT 0,
    proposals_count INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_skill_forge_runs_agent_kind
    ON skill_forge_runs(agent_id, kind, created_at DESC);

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

CREATE TABLE IF NOT EXISTS approval_requests (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    tool_call_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    args_json TEXT NOT NULL DEFAULT '{}',
    risk_level TEXT NOT NULL DEFAULT 'medium',
    summary TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(
        status IN ('pending', 'approved', 'rejected', 'executed', 'failed')
    ),
    result TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_approval_requests_session_status
    ON approval_requests(session_id, status, created_at);

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


_TRUNCATE_SQL = """
TRUNCATE TABLE
    run_metrics,
    subagent_runs,
    skill_forge_runs,
    skills,
    tool_artifacts,
    memory_consolidation_runs,
    memory_injections,
    prompt_snapshots,
    approval_requests,
    compaction_runs,
    context_pacts,
    skill_versions,
    skill_proposals,
    memories,
    tool_calls,
    run_controls,
    runs,
    run_events,
    messages,
    sessions
CASCADE
"""


def ensure_schema(connector: Connector) -> None:
    with connector.connect() as conn:
        conn.executescript(SCHEMA_DDL)


def reset_for_tests(connector: Connector) -> None:
    if not is_test_database_dsn(connector.dsn):
        from ._base import database_name_from_dsn

        dbname = database_name_from_dsn(connector.dsn) or "<unknown>"
        raise RuntimeError(
            "Refusing to reset a non-test database. "
            f"Current database is {dbname!r}; use TOMMY_POSTGRES_DSN with a *_test database."
        )
    with connector.connect() as conn:
        conn.execute(_TRUNCATE_SQL)
