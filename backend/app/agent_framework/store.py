from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .memory import INDEX_ROOT


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, default=str)


def loads(value: str | None) -> Any:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


@dataclass(frozen=True)
class StoredMessage:
    id: str
    session_id: str
    role: str
    content: str
    metadata: dict[str, Any]
    position: int
    created_at: str


class SQLiteAgentStore:
    """SQLite-backed source of truth for local-first agent state."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or INDEX_ROOT / "agent_state.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def ensure_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
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
                        status IN (
                            'queued',
                            'running',
                            'completed',
                            'cancelled',
                            'interrupted',
                            'error'
                        )
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

                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                    USING fts5(memory_id UNINDEXED, agent_id UNINDEXED, content);

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
            )

    def create_session(
        self,
        *,
        session_id: str | None = None,
        agent_id: str = "default",
        title: str = "新对话",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        sid = session_id or f"web-{uuid4().hex}"
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions(
                    id, agent_id, title, preview, summary,
                    metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, '', '', ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    agent_id = excluded.agent_id,
                    updated_at = sessions.updated_at,
                    deleted_at = NULL
                """,
                (sid, agent_id, title, dumps(metadata), now, now),
            )
        return sid

    def ensure_session(self, session_id: str, *, agent_id: str = "default") -> None:
        self.create_session(session_id=session_id, agent_id=agent_id)

    def list_sessions(self, *, agent_id: str = "default") -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, agent_id, title, preview, summary, metadata_json, created_at, updated_at
                FROM sessions
                WHERE agent_id = ? AND deleted_at IS NULL
                ORDER BY updated_at DESC
                """,
                (agent_id,),
            ).fetchall()
        return [dict(row) | {"metadata": loads(row["metadata_json"])} for row in rows]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, agent_id, title, preview, summary, metadata_json, created_at, updated_at
                FROM sessions
                WHERE id = ? AND deleted_at IS NULL
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(row) | {"metadata": loads(row["metadata_json"])}

    def delete_session(self, session_id: str) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                "UPDATE sessions SET deleted_at = ?, updated_at = ? WHERE id = ?",
                (now, now, session_id),
            )

    def append_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> StoredMessage:
        now = utc_now()
        message_id = f"msg-{uuid4().hex}"
        with self.connect() as conn:
            position = (
                conn.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM messages WHERE session_id = ?",
                    (session_id,),
                ).fetchone()[0]
                or 0
            )
            conn.execute(
                """
                INSERT INTO messages(
                    id, session_id, role, content, metadata_json, position, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, session_id, role, content, dumps(metadata), position, now),
            )
            self._refresh_session_summary(conn, session_id)
        return StoredMessage(message_id, session_id, role, content, metadata or {}, position, now)

    def update_message(
        self,
        message_id: str,
        *,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StoredMessage | None:
        updates: list[str] = []
        params: list[Any] = []
        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if metadata is not None:
            updates.append("metadata_json = ?")
            params.append(dumps(metadata))
        if not updates:
            return None

        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, session_id, role, content, metadata_json, position, created_at
                FROM messages
                WHERE id = ?
                """,
                (message_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                f"UPDATE messages SET {', '.join(updates)} WHERE id = ?",
                (*params, message_id),
            )
            self._refresh_session_summary(conn, row["session_id"])
            updated = conn.execute(
                """
                SELECT id, session_id, role, content, metadata_json, position, created_at
                FROM messages
                WHERE id = ?
                """,
                (message_id,),
            ).fetchone()
        if updated is None:
            return None
        return StoredMessage(
            id=updated["id"],
            session_id=updated["session_id"],
            role=updated["role"],
            content=updated["content"],
            metadata=loads(updated["metadata_json"]),
            position=updated["position"],
            created_at=updated["created_at"],
        )

    def list_messages(self, session_id: str, *, limit: int | None = None) -> list[StoredMessage]:
        sql = """
            SELECT id, session_id, role, content, metadata_json, position, created_at
            FROM messages
            WHERE session_id = ?
            ORDER BY position ASC
        """
        params: tuple[Any, ...] = (session_id,)
        if limit is not None:
            sql = f"SELECT * FROM ({sql}) ORDER BY position DESC LIMIT ?"
            params = (session_id, limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        messages = [
            StoredMessage(
                id=row["id"],
                session_id=row["session_id"],
                role=row["role"],
                content=row["content"],
                metadata=loads(row["metadata_json"]),
                position=row["position"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
        return sorted(messages, key=lambda item: item.position)

    def reset_session_content(
        self,
        session_id: str,
        *,
        messages: list[dict[str, Any]] | None = None,
    ) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute("DELETE FROM tool_calls WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM run_events WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            for position, message in enumerate(messages or []):
                conn.execute(
                    """
                    INSERT INTO messages(
                        id, session_id, role, content, metadata_json, position, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"msg-{uuid4().hex}",
                        session_id,
                        message["role"],
                        message["content"],
                        dumps(message.get("metadata")),
                        position,
                        now,
                    ),
                )
            self._refresh_session_summary(conn, session_id)

    def append_run_event(
        self,
        session_id: str,
        *,
        run_id: str,
        type: str,
        label: str,
        status: str = "done",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        event_id = f"evt-{uuid4().hex}"
        with self.connect() as conn:
            sequence = (
                conn.execute(
                    "SELECT COALESCE(MAX(sequence), -1) + 1 FROM run_events WHERE session_id = ?",
                    (session_id,),
                ).fetchone()[0]
                or 0
            )
            conn.execute(
                """
                INSERT INTO run_events(
                    id, session_id, run_id, type, label, status,
                    payload_json, sequence, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, session_id, run_id, type, label, status, dumps(payload), sequence, now),
            )
        return {
            "id": event_id,
            "session_id": session_id,
            "run_id": run_id,
            "type": type,
            "label": label,
            "status": status,
            "payload": payload or {},
            "sequence": sequence,
            "created_at": now,
        }

    def create_run(
        self,
        *,
        session_id: str,
        agent_id: str = "default",
        input: str,
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
        status: str = "queued",
    ) -> dict[str, Any]:
        if status not in {"queued", "running", "completed", "cancelled", "interrupted", "error"}:
            raise ValueError(f"Unsupported run status: {status}")
        rid = run_id or f"run-{uuid4().hex}"
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO runs(
                    id, session_id, agent_id, status, input, metadata_json,
                    assistant_message_id, cancel_requested, created_at, started_at,
                    updated_at, finished_at, error
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, 0, ?, NULL, ?, NULL, '')
                """,
                (rid, session_id, agent_id, status, input, dumps(metadata), now, now),
            )
        run = self.get_run(rid)
        if run is None:
            raise RuntimeError(f"Run was not created: {rid}")
        return run

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return self._run_from_row(row) if row is not None else None

    def update_run_status(
        self,
        run_id: str,
        *,
        status: str | None = None,
        assistant_message_id: str | None = None,
        error: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        updates: list[str] = ["updated_at = ?"]
        params: list[Any] = [utc_now()]
        if status is not None:
            if status not in {
                "queued",
                "running",
                "completed",
                "cancelled",
                "interrupted",
                "error",
            }:
                raise ValueError(f"Unsupported run status: {status}")
            updates.append("status = ?")
            params.append(status)
        if assistant_message_id is not None:
            updates.append("assistant_message_id = ?")
            params.append(assistant_message_id)
        if error is not None:
            updates.append("error = ?")
            params.append(error)
        if started_at is not None:
            updates.append("started_at = ?")
            params.append(started_at)
        if finished_at is not None:
            updates.append("finished_at = ?")
            params.append(finished_at)
        if metadata is not None:
            updates.append("metadata_json = ?")
            params.append(dumps(metadata))
        params.append(run_id)
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            conn.execute(
                f"UPDATE runs SET {', '.join(updates)} WHERE id = ?",
                tuple(params),
            )
        return self.get_run(run_id)

    def request_run_cancel(self, run_id: str) -> dict[str, Any] | None:
        now = utc_now()
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE runs
                SET cancel_requested = 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, run_id),
            )
            conn.execute(
                """
                INSERT INTO run_controls(
                    id, session_id, status, stop_reason,
                    started_at, updated_at, stop_requested_at
                )
                VALUES (?, ?, 'stopping', '用户已停止本次运行', ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = CASE
                        WHEN run_controls.status IN ('completed', 'error', 'stopped')
                            THEN run_controls.status
                        ELSE 'stopping'
                    END,
                    stop_reason = CASE
                        WHEN run_controls.stop_reason != ''
                            THEN run_controls.stop_reason
                        ELSE '用户已停止本次运行'
                    END,
                    updated_at = excluded.updated_at,
                    stop_requested_at = COALESCE(run_controls.stop_requested_at, excluded.stop_requested_at)
                """,
                (run_id, row["session_id"], row["started_at"] or now, now, now),
            )
            conn.execute(
                """
                UPDATE approval_requests
                SET status = 'rejected',
                    error = 'Run was cancelled by user',
                    resolved_at = ?
                WHERE run_id = ? AND status = 'pending'
                """,
                (now, run_id),
            )
        return self.get_run(run_id)

    def is_run_cancel_requested(self, run_id: str) -> bool:
        if not run_id:
            return False
        with self.connect() as conn:
            row = conn.execute(
                "SELECT cancel_requested, status FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        return bool(
            row
            and (
                int(row["cancel_requested"] or 0) == 1
                or row["status"] in {"cancelled", "interrupted"}
            )
        )

    def list_runs(self, session_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM runs
                WHERE session_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def get_latest_run(self, session_id: str) -> dict[str, Any] | None:
        runs = self.list_runs(session_id, limit=1)
        return runs[0] if runs else None

    def get_active_run(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM runs
                WHERE session_id = ?
                  AND status IN ('queued', 'running')
                  AND finished_at IS NULL
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        return self._run_from_row(row) if row is not None else None

    def list_active_runs(self, *, session_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        params: list[Any] = []
        session_clause = ""
        if session_id is not None:
            session_clause = "AND session_id = ?"
            params.append(session_id)
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM runs
                WHERE status IN ('queued', 'running')
                  AND finished_at IS NULL
                  {session_clause}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def list_inflight_runs(
        self,
        *,
        session_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Runs that are still marked queued/running in DB (may be orphans after process restart)."""
        params: list[Any] = []
        session_clause = ""
        if session_id is not None:
            session_clause = "AND session_id = ?"
            params.append(session_id)
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM runs
                WHERE status IN ('queued', 'running')
                  AND finished_at IS NULL
                  {session_clause}
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def finalize_run_as_interrupted(
        self,
        run_id: str,
        *,
        reason: str = "服务进程重启或连接断开后，运行已中断。",
    ) -> dict[str, Any] | None:
        """Mark a non-terminal run as interrupted and persist a terminal run_event for subscribers."""
        now = utc_now()
        event_id = f"evt-{uuid4().hex}"
        agent_event: dict[str, Any] = {
            "type": "interrupted",
            "data": {"status": "interrupted", "reason": reason},
        }
        payload: dict[str, Any] = {
            **agent_event["data"],
            "run_id": run_id,
            "agent_event": agent_event,
        }
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            if row["finished_at"] is not None:
                return self._run_from_row(row)
            if row["status"] not in {"queued", "running"}:
                return self._run_from_row(row)
            session_id = str(row["session_id"])
            sequence = (
                conn.execute(
                    "SELECT COALESCE(MAX(sequence), -1) + 1 FROM run_events WHERE session_id = ?",
                    (session_id,),
                ).fetchone()[0]
                or 0
            )
            conn.execute(
                """
                INSERT INTO run_events(
                    id, session_id, run_id, type, label, status,
                    payload_json, sequence, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    session_id,
                    run_id,
                    "agent",
                    "生成已停止",
                    "done",
                    dumps(payload),
                    sequence,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE runs
                SET status = 'interrupted',
                    finished_at = ?,
                    updated_at = ?,
                    error = ?
                WHERE id = ?
                """,
                (now, now, reason, run_id),
            )
            assistant_message_id = row["assistant_message_id"]
            if assistant_message_id:
                mrow = conn.execute(
                    "SELECT id, session_id, metadata_json FROM messages WHERE id = ?",
                    (assistant_message_id,),
                ).fetchone()
                if mrow is not None:
                    meta = loads(mrow["metadata_json"])
                    meta["status"] = "interrupted"
                    conn.execute(
                        "UPDATE messages SET metadata_json = ? WHERE id = ?",
                        (dumps(meta), assistant_message_id),
                    )
                    self._refresh_session_summary(conn, str(mrow["session_id"]))
            rc = conn.execute(
                "SELECT * FROM run_controls WHERE session_id = ? AND id = ?",
                (session_id, run_id),
            ).fetchone()
            if rc is not None:
                conn.execute(
                    """
                    UPDATE run_controls
                    SET status = 'stopped',
                        stop_reason = ?,
                        updated_at = ?
                    WHERE session_id = ? AND id = ?
                    """,
                    (reason, now, session_id, run_id),
                )
        return self.get_run(run_id)

    def list_run_events_after(
        self,
        run_id: str,
        *,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [run_id]
        sequence_clause = ""
        if after_sequence is not None:
            sequence_clause = "AND sequence > ?"
            params.append(after_sequence)
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, session_id, run_id, type, label, status,
                       payload_json, sequence, created_at
                FROM run_events
                WHERE run_id = ?
                  {sequence_clause}
                ORDER BY sequence ASC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [dict(row) | {"payload": loads(row["payload_json"])} for row in rows]

    def list_run_events(self, session_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT id, session_id, run_id, type, label, status, payload_json, sequence, created_at
            FROM run_events
            WHERE session_id = ?
            ORDER BY sequence ASC
        """
        params: tuple[Any, ...] = (session_id,)
        if limit is not None:
            sql = f"SELECT * FROM ({sql}) ORDER BY sequence DESC LIMIT ?"
            params = (session_id, limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        events = [
            dict(row) | {"payload": loads(row["payload_json"])}
            for row in rows
        ]
        return sorted(events, key=lambda item: item["sequence"])

    def start_run(self, session_id: str, *, run_id: str) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO run_controls(
                    id, session_id, status, stop_reason,
                    started_at, updated_at, stop_requested_at
                )
                VALUES (?, ?, 'running', '', ?, ?, NULL)
                ON CONFLICT(id) DO UPDATE SET
                    session_id = excluded.session_id,
                    status = 'running',
                    stop_reason = '',
                    updated_at = excluded.updated_at,
                    stop_requested_at = NULL
                """,
                (run_id, session_id, now, now),
            )
        return {
            "id": run_id,
            "session_id": session_id,
            "status": "running",
            "stop_reason": "",
            "started_at": now,
            "updated_at": now,
            "stop_requested_at": None,
        }

    def request_run_stop(
        self,
        session_id: str,
        *,
        run_id: str | None = None,
        reason: str = "Stopped by user",
    ) -> list[dict[str, Any]]:
        now = utc_now()
        params: list[Any] = [session_id]
        run_clause = ""
        if run_id:
            run_clause = "AND id = ?"
            params.append(run_id)

        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM run_controls
                WHERE session_id = ?
                  {run_clause}
                  AND status IN ('running', 'stopping')
                ORDER BY updated_at DESC
                """,
                tuple(params),
            ).fetchall()
            if not rows:
                return []

            run_ids = [str(row["id"]) for row in rows]
            placeholders = ",".join("?" for _ in run_ids)
            conn.execute(
                f"""
                UPDATE run_controls
                SET status = 'stopping',
                    stop_reason = ?,
                    stop_requested_at = COALESCE(stop_requested_at, ?),
                    updated_at = ?
                WHERE id IN ({placeholders})
                """,
                (reason, now, now, *run_ids),
            )
            conn.execute(
                f"""
                UPDATE approval_requests
                SET status = 'rejected',
                    error = ?,
                    resolved_at = ?
                WHERE session_id = ?
                  AND run_id IN ({placeholders})
                  AND status = 'pending'
                """,
                (reason, now, session_id, *run_ids),
            )
            updated_rows = conn.execute(
                f"""
                SELECT *
                FROM run_controls
                WHERE id IN ({placeholders})
                ORDER BY updated_at DESC
                """,
                tuple(run_ids),
            ).fetchall()
        return [self._run_control_from_row(row) for row in updated_rows]

    def run_stop_requested(self, *, session_id: str, run_id: str) -> bool:
        if not session_id or not run_id:
            return False
        with self.connect() as conn:
            run_row = conn.execute(
                """
                SELECT cancel_requested, status
                FROM runs
                WHERE session_id = ? AND id = ?
                """,
                (session_id, run_id),
            ).fetchone()
            if run_row and (
                int(run_row["cancel_requested"] or 0) == 1
                or run_row["status"] in {"cancelled", "interrupted"}
            ):
                return True
            row = conn.execute(
                """
                SELECT status
                FROM run_controls
                WHERE session_id = ? AND id = ?
                """,
                (session_id, run_id),
            ).fetchone()
        return bool(row and row["status"] in {"stopping", "stopped"})

    def finish_run(
        self,
        session_id: str,
        *,
        run_id: str,
        status: str,
        reason: str = "",
    ) -> dict[str, Any] | None:
        if status not in {"stopped", "completed", "error"}:
            raise ValueError(f"Unsupported run status: {status}")
        now = utc_now()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM run_controls
                WHERE session_id = ? AND id = ?
                """,
                (session_id, run_id),
            ).fetchone()
            if row is None:
                return None
            next_status = "stopped" if row["status"] == "stopping" else status
            next_reason = reason or row["stop_reason"] or ""
            conn.execute(
                """
                UPDATE run_controls
                SET status = ?,
                    stop_reason = ?,
                    updated_at = ?
                WHERE session_id = ? AND id = ?
                """,
                (next_status, next_reason, now, session_id, run_id),
            )
        with self.connect() as conn:
            updated = conn.execute(
                "SELECT * FROM run_controls WHERE session_id = ? AND id = ?",
                (session_id, run_id),
            ).fetchone()
        return self._run_control_from_row(updated) if updated is not None else None

    def upsert_tool_call(
        self,
        session_id: str,
        *,
        run_id: str,
        tool_call_id: str,
        name: str,
        status: str,
        args: dict[str, Any] | None = None,
        result: str | None = None,
    ) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_calls(
                    id, session_id, run_id, name, status,
                    args_json, result, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    args_json = CASE
                        WHEN excluded.args_json != '{}' THEN excluded.args_json
                        ELSE tool_calls.args_json
                    END,
                    result = CASE
                        WHEN excluded.result != '' THEN excluded.result
                        ELSE tool_calls.result
                    END,
                    updated_at = excluded.updated_at
                """,
                (
                    tool_call_id,
                    session_id,
                    run_id,
                    name,
                    status,
                    dumps(args),
                    result or "",
                    now,
                    now,
                ),
            )

    def list_tool_calls(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id, session_id, run_id, name, status,
                    args_json, result, created_at, updated_at
                FROM tool_calls
                WHERE session_id = ?
                ORDER BY created_at ASC
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) | {"args": loads(row["args_json"])} for row in rows]

    def create_skill_proposal(
        self,
        *,
        agent_id: str,
        name: str,
        relative_path: str,
        action: str,
        rationale: str,
        content: str,
        risks: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "proposed",
    ) -> dict[str, Any]:
        proposal_id = f"skill-prop-{uuid4().hex}"
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO skill_proposals(
                    id, agent_id, name, relative_path, action, rationale, content,
                    risks_json, metadata_json, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal_id,
                    agent_id,
                    name,
                    relative_path,
                    action,
                    rationale,
                    content,
                    dumps(risks or []),
                    dumps(metadata),
                    status,
                    now,
                    now,
                ),
            )
        return {
            "id": proposal_id,
            "agent_id": agent_id,
            "name": name,
            "relative_path": relative_path,
            "action": action,
            "rationale": rationale,
            "content": content,
            "risks": risks or [],
            "metadata": metadata or {},
            "status": status,
            "version_id": None,
            "created_at": now,
            "updated_at": now,
            "applied_at": None,
        }

    def get_skill_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM skill_proposals
                WHERE id = ?
                """,
                (proposal_id,),
            ).fetchone()
        return self._skill_proposal_from_row(row) if row is not None else None

    def list_skill_proposals(
        self,
        *,
        agent_id: str = "default",
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [agent_id]
        status_clause = ""
        if status:
            status_clause = "AND status = ?"
            params.append(status)
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM skill_proposals
                WHERE agent_id = ? {status_clause}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._skill_proposal_from_row(row) for row in rows]

    def apply_skill_proposal(
        self,
        proposal_id: str,
        *,
        version_id: str,
        previous_content: str,
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM skill_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                INSERT INTO skill_versions(
                    id, agent_id, name, relative_path, content,
                    previous_content, proposal_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    row["agent_id"],
                    row["name"],
                    row["relative_path"],
                    row["content"],
                    previous_content,
                    proposal_id,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE skill_proposals
                SET status = 'applied', version_id = ?, updated_at = ?, applied_at = ?
                WHERE id = ?
                """,
                (version_id, now, now, proposal_id),
            )
        proposal = self.get_skill_proposal(proposal_id)
        return proposal

    def reject_skill_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        now = utc_now()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM skill_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE skill_proposals
                SET status = 'rejected', updated_at = ?
                WHERE id = ?
                """,
                (now, proposal_id),
            )
        return self.get_skill_proposal(proposal_id)

    def list_skill_versions(
        self,
        *,
        agent_id: str = "default",
        relative_path: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [agent_id]
        path_clause = ""
        if relative_path:
            path_clause = "AND relative_path = ?"
            params.append(relative_path)
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM skill_versions
                WHERE agent_id = ? {path_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_context_pact(self, session_id: str, *, agent_id: str = "default") -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT pact_json FROM context_pacts
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        return loads(row["pact_json"]) if row is not None else {}

    def upsert_context_pact(
        self,
        session_id: str,
        *,
        agent_id: str = "default",
        pact: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO context_pacts(session_id, agent_id, pact_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    agent_id = excluded.agent_id,
                    pact_json = excluded.pact_json,
                    updated_at = excluded.updated_at
                """,
                (session_id, agent_id, dumps(pact), now, now),
            )
        return pact

    def append_compaction_run(
        self,
        session_id: str,
        *,
        run_id: str | None,
        summary: str,
        message_count: int,
        kept_messages: int,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        compaction_id = f"compact-{uuid4().hex}"
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO compaction_runs(
                    id, session_id, run_id, summary, message_count,
                    kept_messages, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    compaction_id,
                    session_id,
                    run_id,
                    summary,
                    message_count,
                    kept_messages,
                    dumps(metadata),
                    now,
                ),
            )
        return {
            "id": compaction_id,
            "session_id": session_id,
            "run_id": run_id,
            "summary": summary,
            "message_count": message_count,
            "kept_messages": kept_messages,
            "metadata": metadata or {},
            "created_at": now,
        }

    def list_compaction_runs(self, session_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM compaction_runs
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [dict(row) | {"metadata": loads(row["metadata_json"])} for row in rows]

    def create_approval_request(
        self,
        *,
        session_id: str,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        args: dict[str, Any],
        risk_level: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        approval_id = f"approval-{uuid4().hex}"
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO approval_requests(
                    id, session_id, run_id, tool_call_id, tool_name, args_json,
                    risk_level, summary, status, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    approval_id,
                    session_id,
                    run_id,
                    tool_call_id,
                    tool_name,
                    dumps(args),
                    risk_level,
                    summary,
                    dumps(metadata),
                    now,
                ),
            )
        return {
            "id": approval_id,
            "session_id": session_id,
            "run_id": run_id,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "args": args,
            "risk_level": risk_level,
            "summary": summary,
            "status": "pending",
            "result": "",
            "error": "",
            "metadata": metadata or {},
            "created_at": now,
            "resolved_at": None,
        }

    def get_approval_request(self, approval_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM approval_requests WHERE id = ?",
                (approval_id,),
            ).fetchone()
        return self._approval_from_row(row) if row is not None else None

    def list_approval_requests(
        self,
        *,
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM approval_requests
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._approval_from_row(row) for row in rows]

    def resolve_approval_request(
        self,
        approval_id: str,
        *,
        status: str,
        result: str = "",
        error: str = "",
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM approval_requests WHERE id = ?",
                (approval_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE approval_requests
                SET status = ?, result = ?, error = ?, resolved_at = ?
                WHERE id = ?
                """,
                (status, result, error, now, approval_id),
            )
        return self.get_approval_request(approval_id)

    def create_memory(
        self,
        *,
        agent_id: str,
        content: str,
        status: str = "proposed",
        source_session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        memory_id = f"mem-{uuid4().hex}"
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO memories(
                    id, agent_id, content, status, source_session_id,
                    metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    agent_id,
                    content,
                    status,
                    source_session_id,
                    dumps(metadata),
                    now,
                    now,
                ),
            )
            if status == "active":
                conn.execute(
                    "INSERT INTO memories_fts(memory_id, agent_id, content) VALUES (?, ?, ?)",
                    (memory_id, agent_id, content),
                )
        return {
            "id": memory_id,
            "agent_id": agent_id,
            "content": content,
            "status": status,
            "source_session_id": source_session_id,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        }

    def confirm_memory(self, memory_id: str) -> dict[str, Any] | None:
        now = utc_now()
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE memories SET status = 'active', updated_at = ? WHERE id = ?",
                (now, memory_id),
            )
            conn.execute("DELETE FROM memories_fts WHERE memory_id = ?", (memory_id,))
            conn.execute(
                "INSERT INTO memories_fts(memory_id, agent_id, content) VALUES (?, ?, ?)",
                (memory_id, row["agent_id"], row["content"]),
            )
        return dict(row) | {
            "status": "active",
            "updated_at": now,
            "metadata": loads(row["metadata_json"]),
        }

    def list_memories(
        self,
        *,
        agent_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [agent_id]
        status_clause = ""
        if status:
            status_clause = "AND status = ?"
            params.append(status)
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    id, agent_id, content, status, source_session_id,
                    metadata_json, created_at, updated_at
                FROM memories
                WHERE agent_id = ? {status_clause}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [dict(row) | {"metadata": loads(row["metadata_json"])} for row in rows]

    def search_memories(self, *, agent_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        with self.connect() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT
                        m.id, m.agent_id, m.content, m.status, m.source_session_id,
                        m.metadata_json, m.created_at, m.updated_at
                    FROM memories_fts f
                    JOIN memories m ON m.id = f.memory_id
                    WHERE f.agent_id = ? AND memories_fts MATCH ?
                    LIMIT ?
                    """,
                    (agent_id, query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    """
                    SELECT
                        id, agent_id, content, status, source_session_id,
                        metadata_json, created_at, updated_at
                    FROM memories
                    WHERE agent_id = ? AND status = 'active' AND content LIKE ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (agent_id, f"%{query}%", limit),
                ).fetchall()
        return [dict(row) | {"metadata": loads(row["metadata_json"])} for row in rows]

    def _refresh_session_summary(self, conn: sqlite3.Connection, session_id: str) -> None:
        rows = conn.execute(
            """
            SELECT role, content FROM messages
            WHERE session_id = ?
            ORDER BY position ASC
            """,
            (session_id,),
        ).fetchall()
        title = "新对话"
        preview = ""
        for row in rows:
            content = " ".join(row["content"].split())
            if row["role"] == "user" and content and title == "新对话":
                title = content[:24] + ("…" if len(content) > 24 else "")
            if row["role"] == "assistant" and content:
                preview = content[:54] + ("…" if len(content) > 54 else "")
            elif not preview and content:
                preview = content[:54] + ("…" if len(content) > 54 else "")
        now = utc_now()
        conn.execute(
            "UPDATE sessions SET title = ?, preview = ?, updated_at = ? WHERE id = ?",
            (title, preview, now, session_id),
        )

    def set_session_summary(self, session_id: str, summary: str) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                "UPDATE sessions SET summary = ?, updated_at = ? WHERE id = ?",
                (summary, now, session_id),
            )

    def _skill_proposal_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "name": row["name"],
            "relative_path": row["relative_path"],
            "action": row["action"],
            "rationale": row["rationale"],
            "content": row["content"],
            "risks": loads(row["risks_json"]) if row["risks_json"] else [],
            "metadata": loads(row["metadata_json"]),
            "status": row["status"],
            "version_id": row["version_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "applied_at": row["applied_at"],
        }

    def _approval_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "run_id": row["run_id"],
            "tool_call_id": row["tool_call_id"],
            "tool_name": row["tool_name"],
            "args": loads(row["args_json"]),
            "risk_level": row["risk_level"],
            "summary": row["summary"],
            "status": row["status"],
            "result": row["result"],
            "error": row["error"],
            "metadata": loads(row["metadata_json"]),
            "created_at": row["created_at"],
            "resolved_at": row["resolved_at"],
        }

    def _run_control_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "status": row["status"],
            "stop_reason": row["stop_reason"],
            "started_at": row["started_at"],
            "updated_at": row["updated_at"],
            "stop_requested_at": row["stop_requested_at"],
        }

    def _run_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "agent_id": row["agent_id"],
            "status": row["status"],
            "input": row["input"],
            "metadata": loads(row["metadata_json"]),
            "assistant_message_id": row["assistant_message_id"],
            "cancel_requested": bool(row["cancel_requested"]),
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "updated_at": row["updated_at"],
            "finished_at": row["finished_at"],
            "error": row["error"],
        }
