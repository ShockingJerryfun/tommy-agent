from __future__ import annotations

SKILLS_DDL = """
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
"""
