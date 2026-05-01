"""Full-text search repository."""

from __future__ import annotations

from typing import Any

from ._base import Connector


class SearchRepo:
    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def search_messages(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    m.id           AS message_id,
                    m.session_id   AS session_id,
                    m.role         AS role,
                    m.position     AS position,
                    m.created_at   AS created_at,
                    s.title        AS session_title,
                    ts_rank(m.search_tsv, plainto_tsquery('simple', ?)) AS rank,
                    ts_headline(
                        'simple', m.content, plainto_tsquery('simple', ?),
                        'StartSel=<mark>,StopSel=</mark>,MaxWords=20,MinWords=8,MaxFragments=2'
                    ) AS snippet
                FROM messages m
                JOIN sessions s ON s.id = m.session_id AND s.deleted_at IS NULL
                WHERE m.search_tsv @@ plainto_tsquery('simple', ?)
                ORDER BY rank DESC, m.created_at DESC
                LIMIT ?
                """,
                (query, query, query, limit),
            ).fetchall()
        return [dict(row) for row in rows]
