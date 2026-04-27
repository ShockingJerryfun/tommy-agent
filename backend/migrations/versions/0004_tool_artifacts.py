"""tool_artifacts — auto-spill store for large tool outputs

Adds the ``tool_artifacts`` table backing the S4 tool runtime's auto-spill
behaviour: any tool result whose serialised body exceeds the inline
threshold gets written here and the model receives a compact reference
JSON instead of the raw content. Subsequent agent turns can pull the
full body back through the storage facade if they need it.

Columns:

- ``id`` — opaque artifact id (``art-<uuid>``)
- ``session_id`` — owning session (cascade-deleted with the session)
- ``run_id`` — originating run, nullable for utilities
- ``tool_call_id`` — the tool call this artifact came from
- ``tool_name`` — the tool that produced the artifact
- ``kind`` — ``tool_output`` for now; reserved for ``tool_input`` etc.
- ``mime`` — best-effort MIME type (``text/plain`` by default)
- ``size_bytes`` — raw byte length of ``body``
- ``sha256`` — content hash so duplicates can be deduped later
- ``body`` — the full content; PostgreSQL handles arbitrarily large TEXT
- ``metadata_json`` — free-form (e.g. truncation marker, content model)

Revision ID: 0004_tool_artifacts
Revises: 0003_memory_platform
Create Date: 2026-04-27
"""

from __future__ import annotations

from alembic import op

revision = "0004_tool_artifacts"
down_revision = "0003_memory_platform"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
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


DROP_SQL = """
DROP INDEX IF EXISTS idx_tool_artifacts_sha256;
DROP INDEX IF EXISTS idx_tool_artifacts_tool_call;
DROP INDEX IF EXISTS idx_tool_artifacts_session;
DROP TABLE IF EXISTS tool_artifacts;
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
