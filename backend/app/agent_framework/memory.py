from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = ROOT / "data" / "agents"
INDEX_ROOT = ROOT / "data" / "index"
CHECKPOINT_PATH = INDEX_ROOT / "checkpoints.sqlite"
_CHECKPOINT_CONN: sqlite3.Connection | None = None
_CHECKPOINTER: PersistentSqliteSaver | InMemorySaver | None = None
_ASYNC_CHECKPOINT_CONN: aiosqlite.Connection | None = None
_ASYNC_CHECKPOINTER: PersistentAsyncSqliteSaver | None = None


class PersistentSqliteSaver(SqliteSaver):
    def delete_thread(self, thread_id: str) -> None:
        self.setup()
        self.conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
        self.conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        self.conn.commit()

    async def adelete_thread(self, thread_id: str) -> None:
        self.delete_thread(thread_id)


class PersistentAsyncSqliteSaver(AsyncSqliteSaver):
    async def adelete_thread(self, thread_id: str) -> None:
        await self.setup()
        await self.conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
        await self.conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        await self.conn.commit()


def create_checkpointer() -> PersistentSqliteSaver | InMemorySaver:
    global _CHECKPOINT_CONN, _CHECKPOINTER
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER
    INDEX_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        _CHECKPOINT_CONN = sqlite3.connect(CHECKPOINT_PATH, check_same_thread=False)
        _CHECKPOINTER = PersistentSqliteSaver(_CHECKPOINT_CONN)
        _CHECKPOINTER.setup()
    except Exception:
        _CHECKPOINTER = InMemorySaver()
    return _CHECKPOINTER


async def create_async_checkpointer() -> PersistentAsyncSqliteSaver:
    global _ASYNC_CHECKPOINT_CONN, _ASYNC_CHECKPOINTER
    if _ASYNC_CHECKPOINTER is not None:
        return _ASYNC_CHECKPOINTER
    INDEX_ROOT.mkdir(parents=True, exist_ok=True)
    _ASYNC_CHECKPOINT_CONN = await aiosqlite.connect(CHECKPOINT_PATH)
    _ASYNC_CHECKPOINTER = PersistentAsyncSqliteSaver(_ASYNC_CHECKPOINT_CONN)
    await _ASYNC_CHECKPOINTER.setup()
    return _ASYNC_CHECKPOINTER


def build_thread_config(session_id: str) -> dict[str, dict[str, str]]:
    if not session_id:
        raise ValueError("session_id is required to build a LangGraph thread config.")
    return {"configurable": {"thread_id": session_id}}


class LocalMemoryStore:
    def __init__(self, agent_id: str = "default", root: Path | None = None) -> None:
        self.agent_id = agent_id
        self.agent_root = (root or DATA_ROOT) / agent_id
        self.session_root = self.agent_root / "sessions"
        self.memory_root = self.agent_root / "memory"
        self.index_path = INDEX_ROOT / "memory.sqlite"

    def ensure_layout(self) -> None:
        self.session_root.mkdir(parents=True, exist_ok=True)
        self.memory_root.mkdir(parents=True, exist_ok=True)
        INDEX_ROOT.mkdir(parents=True, exist_ok=True)
        for name, content in {
            "SOUL.md": "# SOUL\n",
            "MEMORY.md": "# MEMORY\n",
            "USER.md": "# USER\n",
            "DREAMS.md": "# DREAMS\n",
        }.items():
            path = self.agent_root / name
            if not path.exists():
                path.write_text(content, encoding="utf-8")
        self._ensure_index()

    def append_session_event(self, session_id: str, event: dict[str, Any]) -> None:
        self.ensure_layout()
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "session_id": session_id,
            **event,
        }
        path = self.session_root / f"{session_id}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def append_daily_memory(self, content: str) -> Path:
        self.ensure_layout()
        path = self.memory_root / f"{datetime.now(UTC).date().isoformat()}.md"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n- {datetime.now(UTC).isoformat()} {content}\n")
        self.index_memory_file(path)
        return path

    def _ensure_index(self) -> None:
        with sqlite3.connect(self.index_path) as conn:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(agent_id, path, content)"
            )
            conn.commit()

    def index_memory_file(self, path: Path) -> None:
        self._ensure_index()
        content = path.read_text(encoding="utf-8", errors="replace")
        relative = str(path.relative_to(self.agent_root))
        with sqlite3.connect(self.index_path) as conn:
            conn.execute(
                "DELETE FROM memory_fts WHERE agent_id = ? AND path = ?",
                (self.agent_id, relative),
            )
            conn.execute(
                "INSERT INTO memory_fts(agent_id, path, content) VALUES (?, ?, ?)",
                (self.agent_id, relative, content),
            )
            conn.commit()

    def search(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        self._ensure_index()
        with sqlite3.connect(self.index_path) as conn:
            rows = conn.execute(
                """
                SELECT path, snippet(memory_fts, 2, '[', ']', '...', 20) AS snippet
                FROM memory_fts
                WHERE agent_id = ? AND memory_fts MATCH ?
                LIMIT ?
                """,
                (self.agent_id, query, limit),
            ).fetchall()
        return [{"path": path, "snippet": snippet} for path, snippet in rows]
