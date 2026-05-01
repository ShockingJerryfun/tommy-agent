from __future__ import annotations

from typing import Any

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row

from ..settings import load_settings

_CHECKPOINT_CONN: psycopg.Connection[Any] | None = None
_CHECKPOINTER: PostgresSaver | None = None
_ASYNC_CHECKPOINT_CONN: Any | None = None
_ASYNC_CHECKPOINTER: AsyncPostgresSaver | None = None


class PersistentAsyncPostgresSaver(AsyncPostgresSaver):
    async def adelete_thread(self, thread_id: str) -> None:
        await self.setup()
        await self.conn.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s", (thread_id,))
        await self.conn.execute("DELETE FROM checkpoints WHERE thread_id = %s", (thread_id,))
        await self.conn.commit()


class PersistentPostgresSaver(PostgresSaver):
    def delete_thread(self, thread_id: str) -> None:
        self.setup()
        self.conn.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s", (thread_id,))
        self.conn.execute("DELETE FROM checkpoints WHERE thread_id = %s", (thread_id,))
        self.conn.commit()

    async def adelete_thread(self, thread_id: str) -> None:
        self.delete_thread(thread_id)


def create_checkpointer() -> PersistentPostgresSaver:
    global _CHECKPOINT_CONN, _CHECKPOINTER
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER
    _CHECKPOINT_CONN = psycopg.connect(
        load_settings().postgres_dsn,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    _CHECKPOINTER = PersistentPostgresSaver(_CHECKPOINT_CONN)
    _CHECKPOINTER.setup()
    return _CHECKPOINTER


async def create_async_checkpointer() -> PersistentAsyncPostgresSaver:
    global _ASYNC_CHECKPOINT_CONN, _ASYNC_CHECKPOINTER
    if _ASYNC_CHECKPOINTER is not None:
        return _ASYNC_CHECKPOINTER
    _ASYNC_CHECKPOINT_CONN = await psycopg.AsyncConnection.connect(
        load_settings().postgres_dsn,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    _ASYNC_CHECKPOINTER = PersistentAsyncPostgresSaver(_ASYNC_CHECKPOINT_CONN)
    await _ASYNC_CHECKPOINTER.setup()
    return _ASYNC_CHECKPOINTER


def build_thread_config(session_id: str) -> dict[str, dict[str, str]]:
    if not session_id:
        raise ValueError("session_id is required to build a LangGraph thread config.")
    return {"configurable": {"thread_id": session_id}}


def checkpoint_status() -> dict[str, object]:
    return {
        "backend": "postgres",
        "dsn_configured": bool(load_settings().postgres_dsn),
        "sync_initialized": _CHECKPOINTER is not None,
        "async_initialized": _ASYNC_CHECKPOINTER is not None,
    }
