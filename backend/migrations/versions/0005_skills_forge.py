"""skills + skill_forge_runs — Skills & Forge data plane

Adds the canonical ``skills`` table (the activator's index) and the
``skill_forge_runs`` audit log used by the nightly Forge pipeline. The
existing ``skill_proposals`` and ``skill_versions`` tables remain the
human-review queue and the changelog respectively; the new ``skills``
row represents the *active* catalog entry the activator searches over
with HNSW on a signature embedding.

Status lifecycle (column ``status`` on ``skills``):

- ``shadow``  — Forge produced a candidate; metrics are still being
  collected via shadow validation. Not yet visible to the activator.
- ``active``  — Promoted (currently always via human review) and
  searchable through ``SkillCatalogRepo.search_signature``.
- ``retired`` — Demoted by Forge or operator; kept for audit.

Revision ID: 0005_skills_forge
Revises: 0004_tool_artifacts
Create Date: 2026-04-27
"""

from __future__ import annotations

from alembic import op

revision = "0005_skills_forge"
down_revision = "0004_tool_artifacts"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

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
"""


DROP_SQL = """
DROP INDEX IF EXISTS idx_skill_forge_runs_agent_kind;
DROP TABLE IF EXISTS skill_forge_runs;
DROP INDEX IF EXISTS idx_skills_signature_hnsw;
DROP INDEX IF EXISTS idx_skills_agent_status_updated;
DROP TABLE IF EXISTS skills;
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
