"""Shared low-level helpers for repository modules.

The application keeps using ``psycopg`` directly. This module provides the
shared connection wrapper, JSON helpers, and the ``StoredMessage`` value object
that every repository depends on.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row


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


def database_name_from_dsn(dsn: str) -> str:
    try:
        params = conninfo_to_dict(dsn)
    except psycopg.ProgrammingError:
        return ""
    return str(params.get("dbname") or params.get("database") or "")


def is_test_database_dsn(dsn: str) -> bool:
    dbname = database_name_from_dsn(dsn).lower()
    return dbname.endswith("_test") or dbname.startswith("test_")


@dataclass(frozen=True)
class StoredMessage:
    id: str
    session_id: str
    role: str
    content: str
    metadata: dict[str, Any]
    position: int
    created_at: str


def to_pg_sql(sql: str) -> str:
    """Translate the historical ``?`` placeholder dialect to psycopg's ``%s``."""
    return sql.replace("?", "%s")


class PostgresRow(dict[str, Any]):
    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class PostgresCursor:
    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def fetchone(self) -> PostgresRow | None:
        row = self._cursor.fetchone()
        return PostgresRow(row) if row is not None else None

    def fetchall(self) -> list[PostgresRow]:
        return [PostgresRow(row) for row in self._cursor.fetchall()]


class PostgresConnection:
    """Thin wrapper that normalises placeholders and exposes our row type."""

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> PostgresCursor:
        return PostgresCursor(self._conn.execute(to_pg_sql(sql), params))

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            sql = statement.strip()
            if sql:
                self.execute(sql)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


class Connector:
    """Owns the DSN and yields short-lived autocommit-off connections.

    Each repository receives the same Connector instance so all operations
    share the same connection policy (``prepare_threshold=0`` for pgbouncer
    safety; ``dict_row`` so callers see column names).
    """

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @contextmanager
    def connect(self) -> Iterator[PostgresConnection]:
        conn = PostgresConnection(
            psycopg.connect(
                self.dsn,
                autocommit=False,
                prepare_threshold=0,
                row_factory=dict_row,
            )
        )
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def refresh_session_summary(conn: PostgresConnection, session_id: str) -> None:
    """Recompute ``sessions.title``/``preview`` from the current message tail.

    Shared by the session and message repositories so writes from either
    side keep the session card up to date in one place.
    """

    first_user = conn.execute(
        """
        SELECT role, content FROM messages
        WHERE session_id = ? AND role = 'user' AND content <> ''
        ORDER BY position ASC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    latest_assistant = conn.execute(
        """
        SELECT role, content FROM messages
        WHERE session_id = ? AND role = 'assistant' AND content <> ''
        ORDER BY position DESC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    latest_message = conn.execute(
        """
        SELECT role, content FROM messages
        WHERE session_id = ? AND content <> ''
        ORDER BY position DESC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()

    title = "新对话"
    preview = ""
    if first_user is not None:
        content = " ".join(str(first_user["content"]).split())
        if content:
            title = content[:24] + ("…" if len(content) > 24 else "")
    preview_source = latest_assistant or latest_message
    if preview_source is not None:
        content = " ".join(str(preview_source["content"]).split())
        if content:
            preview = content[:54] + ("…" if len(content) > 54 else "")

    now = utc_now()
    conn.execute(
        "UPDATE sessions SET title = ?, preview = ?, updated_at = ? WHERE id = ?",
        (title, preview, now, session_id),
    )
