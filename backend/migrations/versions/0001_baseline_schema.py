"""baseline schema

S0 baseline. Mirrors the schema previously created by
``PostgresAgentStore.ensure_schema``. All statements are idempotent so
existing databases (already provisioned by ``ensure_schema``) can be
stamped without diffs and brand-new databases can be brought up via
``alembic upgrade head``.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-04-27
"""

from __future__ import annotations

from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


SCHEMA_SQL = """
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

CREATE INDEX IF NOT EXISTS idx_memories_agent_status_updated
    ON memories(agent_id, status, updated_at);

CREATE INDEX IF NOT EXISTS idx_memories_content_trgm
    ON memories USING GIN (content gin_trgm_ops);

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
"""


DROP_SQL = """
DROP TABLE IF EXISTS approval_requests CASCADE;
DROP TABLE IF EXISTS compaction_runs CASCADE;
DROP TABLE IF EXISTS context_pacts CASCADE;
DROP TABLE IF EXISTS skill_versions CASCADE;
DROP TABLE IF EXISTS skill_proposals CASCADE;
DROP TABLE IF EXISTS memories CASCADE;
DROP TABLE IF EXISTS tool_calls CASCADE;
DROP TABLE IF EXISTS run_controls CASCADE;
DROP TABLE IF EXISTS runs CASCADE;
DROP TABLE IF EXISTS run_events CASCADE;
DROP TABLE IF EXISTS messages CASCADE;
DROP TABLE IF EXISTS sessions CASCADE;
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    op.execute(DROP_SQL)
