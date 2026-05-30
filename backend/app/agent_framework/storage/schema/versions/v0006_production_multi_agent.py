from __future__ import annotations

PRODUCTION_MULTI_AGENT_DDL = """
ALTER TABLE subagent_runs ADD COLUMN IF NOT EXISTS role_id TEXT NOT NULL DEFAULT '';
ALTER TABLE subagent_runs ADD COLUMN IF NOT EXISTS agent_definition_id TEXT NOT NULL DEFAULT '';
ALTER TABLE subagent_runs ADD COLUMN IF NOT EXISTS team_id TEXT NOT NULL DEFAULT '';
ALTER TABLE subagent_runs ADD COLUMN IF NOT EXISTS team_run_id TEXT NOT NULL DEFAULT '';
ALTER TABLE subagent_runs ADD COLUMN IF NOT EXISTS team_task_id TEXT NOT NULL DEFAULT '';
ALTER TABLE subagent_runs ADD COLUMN IF NOT EXISTS workflow_run_id TEXT NOT NULL DEFAULT '';
ALTER TABLE subagent_runs ADD COLUMN IF NOT EXISTS phase_run_id TEXT NOT NULL DEFAULT '';
ALTER TABLE subagent_runs ADD COLUMN IF NOT EXISTS workflow_phase_id TEXT NOT NULL DEFAULT '';
ALTER TABLE subagent_runs ADD COLUMN IF NOT EXISTS approval_id TEXT NOT NULL DEFAULT '';
ALTER TABLE subagent_runs ADD COLUMN IF NOT EXISTS error_type TEXT NOT NULL DEFAULT '';
ALTER TABLE subagent_runs ADD COLUMN IF NOT EXISTS error_message TEXT NOT NULL DEFAULT '';
ALTER TABLE subagent_runs ADD COLUMN IF NOT EXISTS started_at TEXT;

UPDATE subagent_runs
SET role_id = role
WHERE role_id = '';

UPDATE subagent_runs
SET agent_definition_id = role
WHERE agent_definition_id = '';

UPDATE subagent_runs
SET started_at = created_at
WHERE started_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_subagent_runs_parent_run_id
    ON subagent_runs(parent_run_id);

CREATE INDEX IF NOT EXISTS idx_subagent_runs_team_task
    ON subagent_runs(team_id, team_task_id);

CREATE INDEX IF NOT EXISTS idx_subagent_runs_workflow_phase
    ON subagent_runs(workflow_run_id, phase_run_id);

CREATE INDEX IF NOT EXISTS idx_subagent_runs_status_created
    ON subagent_runs(status, created_at);

CREATE TABLE IF NOT EXISTS agent_team_runs (
    id TEXT PRIMARY KEY,
    team_id TEXT NOT NULL REFERENCES agent_teams(id) ON DELETE CASCADE,
    parent_session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    parent_run_id TEXT NOT NULL,
    approval_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK(status IN (
            'queued', 'running', 'completed', 'failed', 'stopped', 'cancelled', 'interrupted'
        )),
    goal TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_agent_team_runs_team_status
    ON agent_team_runs(team_id, status);

CREATE INDEX IF NOT EXISTS idx_agent_team_runs_parent_status
    ON agent_team_runs(parent_run_id, status);

ALTER TABLE agent_team_tasks ADD COLUMN IF NOT EXISTS team_run_id TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_team_tasks ADD COLUMN IF NOT EXISTS started_at TEXT;
ALTER TABLE agent_team_tasks ADD COLUMN IF NOT EXISTS error_type TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_team_tasks ADD COLUMN IF NOT EXISTS error_message TEXT NOT NULL DEFAULT '';

ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS started_at TEXT;
ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS error_type TEXT NOT NULL DEFAULT '';
ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS error_message TEXT NOT NULL DEFAULT '';

UPDATE workflow_runs
SET started_at = created_at
WHERE started_at IS NULL AND status = 'running';

CREATE INDEX IF NOT EXISTS idx_workflow_runs_parent_status
    ON workflow_runs(parent_run_id, status);

ALTER TABLE workflow_phase_runs ADD COLUMN IF NOT EXISTS started_at TEXT;
ALTER TABLE workflow_phase_runs ADD COLUMN IF NOT EXISTS error_type TEXT NOT NULL DEFAULT '';
ALTER TABLE workflow_phase_runs ADD COLUMN IF NOT EXISTS error_message TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_workflow_phase_runs_status
    ON workflow_phase_runs(workflow_run_id, status);

ALTER TABLE workflow_worker_runs ADD COLUMN IF NOT EXISTS started_at TEXT;
ALTER TABLE workflow_worker_runs ADD COLUMN IF NOT EXISTS error_type TEXT NOT NULL DEFAULT '';
ALTER TABLE workflow_worker_runs ADD COLUMN IF NOT EXISTS error_message TEXT NOT NULL DEFAULT '';
ALTER TABLE workflow_worker_runs ADD COLUMN IF NOT EXISTS cache_key TEXT NOT NULL DEFAULT '';
ALTER TABLE workflow_worker_runs ADD COLUMN IF NOT EXISTS input_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE workflow_worker_runs ADD COLUMN IF NOT EXISTS cache_hit INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_workflow_worker_runs_phase
    ON workflow_worker_runs(workflow_run_id, phase_run_id);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    owner_run_id TEXT NOT NULL,
    owner_type TEXT NOT NULL,
    subagent_run_id TEXT NOT NULL DEFAULT '',
    team_run_id TEXT NOT NULL DEFAULT '',
    workflow_run_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    uri TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_artifacts_subagent_run
    ON artifacts(subagent_run_id);

CREATE INDEX IF NOT EXISTS idx_artifacts_owner_run
    ON artifacts(owner_run_id);
"""
