from __future__ import annotations

CORE_DDL = """
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    title TEXT NOT NULL,
    preview TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    pinned BOOLEAN NOT NULL DEFAULT FALSE,
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    share_token TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

ALTER TABLE sessions ADD COLUMN IF NOT EXISTS pinned BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS share_token TEXT;

CREATE INDEX IF NOT EXISTS idx_sessions_agent_deleted_updated
    ON sessions(agent_id, deleted_at, updated_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS ix_sessions_share_token
    ON sessions(share_token) WHERE share_token IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sessions_pinned_archived_updated
    ON sessions(agent_id, pinned DESC, archived, updated_at DESC)
    WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    position INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

ALTER TABLE messages ADD COLUMN IF NOT EXISTS search_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('simple', coalesce(content, ''))) STORED;

CREATE INDEX IF NOT EXISTS idx_messages_session_position
    ON messages(session_id, position);

CREATE INDEX IF NOT EXISTS idx_messages_session_role_position
    ON messages(session_id, role, position);

CREATE INDEX IF NOT EXISTS idx_messages_search_tsv
    ON messages USING GIN (search_tsv);

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
    idempotency_key TEXT,
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

ALTER TABLE runs ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS ix_runs_idempotency
    ON runs(session_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

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
"""
