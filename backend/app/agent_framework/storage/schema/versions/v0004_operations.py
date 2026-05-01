from __future__ import annotations

OPERATIONS_DDL = """
CREATE TABLE IF NOT EXISTS run_metrics (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT 'default',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms REAL NOT NULL DEFAULT 0.0,
    model TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    reasoning_tokens INTEGER,
    finish_reason TEXT,
    status TEXT,
    error_count INTEGER NOT NULL DEFAULT 0,
    cancelled BOOLEAN NOT NULL DEFAULT FALSE,
    interrupted BOOLEAN NOT NULL DEFAULT FALSE,
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

ALTER TABLE run_metrics ADD COLUMN IF NOT EXISTS model TEXT;
ALTER TABLE run_metrics ADD COLUMN IF NOT EXISTS prompt_tokens INTEGER;
ALTER TABLE run_metrics ADD COLUMN IF NOT EXISTS completion_tokens INTEGER;
ALTER TABLE run_metrics ADD COLUMN IF NOT EXISTS total_tokens INTEGER;
ALTER TABLE run_metrics ADD COLUMN IF NOT EXISTS reasoning_tokens INTEGER;
ALTER TABLE run_metrics ADD COLUMN IF NOT EXISTS finish_reason TEXT;
ALTER TABLE run_metrics ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE run_metrics ADD COLUMN IF NOT EXISTS error_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE run_metrics ADD COLUMN IF NOT EXISTS cancelled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE run_metrics ADD COLUMN IF NOT EXISTS interrupted BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS prompts (
    id TEXT PRIMARY KEY,
    owner_user TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL CHECK(kind IN ('builtin', 'user')),
    name TEXT NOT NULL,
    body TEXT NOT NULL,
    shortcut TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prompts_owner
    ON prompts(owner_user, kind);

CREATE UNIQUE INDEX IF NOT EXISTS ux_prompts_shortcut
    ON prompts(owner_user, shortcut)
    WHERE shortcut <> '';

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
