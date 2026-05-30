"""Agent team persistence repositories."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ._base import Connector, dumps, loads, utc_now


class AgentTeamRepo:
    SELECT_COLUMNS = (
        "id, parent_session_id, parent_run_id, goal, status, lead_member_id, "
        "metadata_json, created_at, updated_at, finished_at"
    )

    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def create(
        self,
        *,
        parent_session_id: str,
        parent_run_id: str,
        goal: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        team_id = f"team-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_teams(
                    id, parent_session_id, parent_run_id, goal, status, lead_member_id,
                    metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'queued', '', ?, ?, ?)
                """,
                (team_id, parent_session_id, parent_run_id, goal, dumps(metadata), now, now),
            )
        return self.get(team_id) or {}

    def update(
        self,
        team_id: str,
        *,
        status: str | None = None,
        lead_member_id: str | None = None,
        metadata_patch: dict[str, Any] | None = None,
        finished: bool = False,
    ) -> dict[str, Any] | None:
        existing = self.get(team_id)
        if existing is None:
            return None
        metadata = dict(existing.get("metadata") or {})
        if metadata_patch:
            metadata.update(metadata_patch)
        new_status = status or existing["status"]
        now = utc_now()
        finished_at = now if finished or new_status in {"completed", "failed", "stopped"} else None
        with self._connector.connect() as conn:
            conn.execute(
                """
                UPDATE agent_teams
                SET status = ?, lead_member_id = ?, metadata_json = ?, updated_at = ?,
                    finished_at = COALESCE(?, finished_at)
                WHERE id = ?
                """,
                (
                    new_status,
                    lead_member_id if lead_member_id is not None else existing["lead_member_id"],
                    dumps(metadata),
                    now,
                    finished_at,
                    team_id,
                ),
            )
        return self.get(team_id)

    def get(self, team_id: str) -> dict[str, Any] | None:
        with self._connector.connect() as conn:
            row = conn.execute(
                f"SELECT {self.SELECT_COLUMNS} FROM agent_teams WHERE id = ?",
                (team_id,),
            ).fetchone()
        return _hydrate_team(row) if row is not None else None

    def list_for_session(self, parent_session_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM agent_teams
                WHERE parent_session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (parent_session_id, limit),
            ).fetchall()
        return [_hydrate_team(row) for row in rows]


class AgentTeamMemberRepo:
    SELECT_COLUMNS = (
        "id, team_id, role, agent_definition_id, session_id, run_id, status, "
        "metadata_json, created_at, updated_at, finished_at"
    )

    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def create(
        self,
        *,
        team_id: str,
        role: str,
        agent_definition_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        member_id = f"member-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_team_members(
                    id, team_id, role, agent_definition_id, session_id, run_id,
                    status, metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, '', '', 'queued', ?, ?, ?)
                """,
                (member_id, team_id, role, agent_definition_id, dumps(metadata), now, now),
            )
        return self.get(member_id) or {}

    def get(self, member_id: str) -> dict[str, Any] | None:
        with self._connector.connect() as conn:
            row = conn.execute(
                f"SELECT {self.SELECT_COLUMNS} FROM agent_team_members WHERE id = ?",
                (member_id,),
            ).fetchone()
        return _hydrate_member(row) if row is not None else None

    def list_for_team(self, team_id: str) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM agent_team_members
                WHERE team_id = ?
                ORDER BY created_at ASC
                """,
                (team_id,),
            ).fetchall()
        return [_hydrate_member(row) for row in rows]


class AgentTeamTaskRepo:
    SELECT_COLUMNS = (
        "id, team_id, team_run_id, title, description, status, priority, assigned_member_id, "
        "dependencies_json, result_subagent_id, result_summary, metadata_json, "
        "error_type, error_message, created_at, started_at, updated_at, finished_at"
    )

    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def create(
        self,
        *,
        team_id: str,
        title: str,
        description: str,
        assigned_member_id: str = "",
        team_run_id: str = "",
        dependencies: list[str] | None = None,
        priority: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_id = f"team-task-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_team_tasks(
                    id, team_id, team_run_id, title, description, status, priority,
                    assigned_member_id,
                    dependencies_json, result_subagent_id, result_summary, metadata_json,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, '', '', ?, ?, ?)
                """,
                (
                    task_id,
                    team_id,
                    team_run_id,
                    title,
                    description,
                    int(priority),
                    assigned_member_id,
                    dumps(dependencies or []),
                    dumps(metadata),
                    now,
                    now,
                ),
            )
        return self.get(task_id) or {}

    def update(
        self,
        task_id: str,
        *,
        status: str | None = None,
        assigned_member_id: str | None = None,
        result_subagent_id: str | None = None,
        result_summary: str | None = None,
        team_run_id: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        metadata_patch: dict[str, Any] | None = None,
        finished: bool = False,
    ) -> dict[str, Any] | None:
        existing = self.get(task_id)
        if existing is None:
            return None
        metadata = dict(existing.get("metadata") or {})
        if metadata_patch:
            metadata.update(metadata_patch)
        new_status = status or existing["status"]
        now = utc_now()
        finished_at = now if finished or new_status in {"completed", "failed", "stopped"} else None
        started_at = now if new_status == "running" and not existing.get("started_at") else None
        with self._connector.connect() as conn:
            conn.execute(
                """
                UPDATE agent_team_tasks
                SET status = ?, team_run_id = ?, assigned_member_id = ?,
                    result_subagent_id = ?, result_summary = ?, error_type = ?,
                    error_message = ?, metadata_json = ?,
                    started_at = COALESCE(started_at, ?), updated_at = ?,
                    finished_at = COALESCE(?, finished_at)
                WHERE id = ?
                """,
                (
                    new_status,
                    team_run_id if team_run_id is not None else existing["team_run_id"],
                    assigned_member_id
                    if assigned_member_id is not None
                    else existing["assigned_member_id"],
                    result_subagent_id
                    if result_subagent_id is not None
                    else existing["result_subagent_id"],
                    result_summary if result_summary is not None else existing["result_summary"],
                    error_type if error_type is not None else existing["error_type"],
                    error_message if error_message is not None else existing["error_message"],
                    dumps(metadata),
                    started_at,
                    now,
                    finished_at,
                    task_id,
                ),
            )
        return self.get(task_id)

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._connector.connect() as conn:
            row = conn.execute(
                f"SELECT {self.SELECT_COLUMNS} FROM agent_team_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        return _hydrate_task(row) if row is not None else None

    def list_for_team(self, team_id: str) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM agent_team_tasks
                WHERE team_id = ?
                ORDER BY priority DESC, created_at ASC
                """,
                (team_id,),
            ).fetchall()
        return [_hydrate_task(row) for row in rows]


class AgentTeamRunRepo:
    SELECT_COLUMNS = (
        "id, team_id, parent_session_id, parent_run_id, approval_id, status, goal, "
        "summary, started_at, finished_at, created_at, updated_at, metadata_json"
    )

    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def create(
        self,
        *,
        team_id: str,
        parent_session_id: str,
        parent_run_id: str,
        approval_id: str = "",
        goal: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = f"team-run-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_team_runs(
                    id, team_id, parent_session_id, parent_run_id, approval_id, status,
                    goal, summary, created_at, updated_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, 'queued', ?, '', ?, ?, ?)
                """,
                (
                    run_id,
                    team_id,
                    parent_session_id,
                    parent_run_id,
                    approval_id,
                    goal,
                    now,
                    now,
                    dumps(metadata),
                ),
            )
        return self.get(run_id) or {}

    def update(
        self,
        run_id: str,
        *,
        status: str | None = None,
        summary: str | None = None,
        metadata_patch: dict[str, Any] | None = None,
        finished: bool = False,
    ) -> dict[str, Any] | None:
        existing = self.get(run_id)
        if existing is None:
            return None
        metadata = dict(existing.get("metadata") or {})
        if metadata_patch:
            metadata.update(metadata_patch)
        new_status = status or existing["status"]
        now = utc_now()
        started_at = now if new_status == "running" and not existing.get("started_at") else None
        finished_at = (
            now
            if finished
            or new_status in {"completed", "failed", "stopped", "cancelled", "interrupted"}
            else None
        )
        with self._connector.connect() as conn:
            conn.execute(
                """
                UPDATE agent_team_runs
                SET status = ?, summary = ?, metadata_json = ?,
                    started_at = COALESCE(started_at, ?), updated_at = ?,
                    finished_at = COALESCE(?, finished_at)
                WHERE id = ?
                """,
                (
                    new_status,
                    summary if summary is not None else existing["summary"],
                    dumps(metadata),
                    started_at,
                    now,
                    finished_at,
                    run_id,
                ),
            )
        return self.get(run_id)

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._connector.connect() as conn:
            row = conn.execute(
                f"SELECT {self.SELECT_COLUMNS} FROM agent_team_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        return _hydrate_team_run(row) if row is not None else None

    def list_for_team(self, team_id: str) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM agent_team_runs
                WHERE team_id = ?
                ORDER BY created_at DESC
                """,
                (team_id,),
            ).fetchall()
        return [_hydrate_team_run(row) for row in rows]

    def list_for_parent_run(self, parent_run_id: str) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM agent_team_runs
                WHERE parent_run_id = ?
                ORDER BY created_at DESC
                """,
                (parent_run_id,),
            ).fetchall()
        return [_hydrate_team_run(row) for row in rows]

    def list_running(self) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM agent_team_runs
                WHERE status = 'running'
                ORDER BY created_at ASC
                """
            ).fetchall()
        return [_hydrate_team_run(row) for row in rows]

    def mark_running_background_jobs_interrupted(self) -> int:
        rows = self.list_running()
        now = utc_now()
        with self._connector.connect() as conn:
            for row in rows:
                conn.execute(
                    """
                    UPDATE agent_team_runs
                    SET status = 'interrupted',
                        metadata_json = ?,
                        updated_at = ?,
                        finished_at = COALESCE(finished_at, ?)
                    WHERE id = ?
                    """,
                    (
                        dumps(
                            {
                                **dict(row.get("metadata") or {}),
                                "interrupted_reason": (
                                    "Background process restarted while team was running."
                                ),
                            }
                        ),
                        now,
                        now,
                        row["id"],
                    ),
                )
        return len(rows)


class AgentTeamMessageRepo:
    SELECT_COLUMNS = (
        "id, team_id, from_member_id, to_member_id, task_id, kind, content, "
        "metadata_json, created_at"
    )

    def __init__(self, connector: Connector) -> None:
        self._connector = connector

    def create(
        self,
        *,
        team_id: str,
        content: str,
        from_member_id: str = "",
        to_member_id: str = "",
        task_id: str = "",
        kind: str = "note",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message_id = f"team-msg-{uuid4().hex}"
        now = utc_now()
        with self._connector.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_team_messages(
                    id, team_id, from_member_id, to_member_id, task_id, kind,
                    content, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    team_id,
                    from_member_id,
                    to_member_id,
                    task_id,
                    kind,
                    content,
                    dumps(metadata),
                    now,
                ),
            )
        return {"id": message_id, "team_id": team_id, "content": content, "created_at": now}

    def list_for_team(self, team_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connector.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.SELECT_COLUMNS}
                FROM agent_team_messages
                WHERE team_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (team_id, int(limit)),
            ).fetchall()
        messages = [_hydrate_message(row) for row in rows]
        return list(reversed(messages))


def _hydrate_team_run(row: Any) -> dict[str, Any]:
    return dict(row) | {"metadata": loads(row["metadata_json"])}


def _hydrate_team(row: Any) -> dict[str, Any]:
    return dict(row) | {"metadata": loads(row["metadata_json"])}


def _hydrate_member(row: Any) -> dict[str, Any]:
    return dict(row) | {"metadata": loads(row["metadata_json"])}


def _hydrate_task(row: Any) -> dict[str, Any]:
    return dict(row) | {
        "dependencies": loads(row["dependencies_json"]) or [],
        "metadata": loads(row["metadata_json"]),
    }


def _hydrate_message(row: Any) -> dict[str, Any]:
    return dict(row) | {"metadata": loads(row["metadata_json"])}
