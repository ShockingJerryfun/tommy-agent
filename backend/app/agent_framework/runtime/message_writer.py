from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

from ..storage.interfaces import MessageRecord, MessageStore


class AssistantMessageWriter:
    """Accumulates assistant text/tool parts and persists them at a bounded cadence.

    Contract (S0):

    * The writer is the **only** path that mutates the assistant message
      row during a run. Graph nodes append text/tool parts here; the
      run service flushes at well-defined lifecycle points.
    * ``flush()`` honors a token-count threshold and a wall-clock
      threshold so streaming is responsive but write amplification is
      bounded, regardless of token rate.
    * ``flush(force=True)`` is the single terminal write — ``status``
      transitions ("running" → "completed"/"cancelled"/"interrupted"/
      "error") always force-flush so the persisted message reflects the
      final state exactly once.
    * The accumulator is fully in-memory; failure of the underlying
      ``MessageStore.update_message`` propagates to the caller so the
      run service can downgrade to the appropriate terminal status.
    """

    def __init__(
        self,
        *,
        store: MessageStore,
        message: MessageRecord,
        run_id: str,
        min_tokens_between_flushes: int = 64,
        max_seconds_between_flushes: float = 0.8,
    ) -> None:
        self._store = store
        self._message = message
        self._run_id = run_id
        self._min_tokens_between_flushes = min_tokens_between_flushes
        self._max_seconds_between_flushes = max_seconds_between_flushes
        self._tokens: list[str] = []
        self._parts: list[dict[str, Any]] = []
        self._tokens_since_flush = 0
        self._last_flush_at = time.monotonic()
        self._flushed_content = ""
        self._flushed_parts_json = "[]"
        self._flushed_status = "running"

    @property
    def content(self) -> str:
        return "".join(self._tokens)

    @property
    def parts(self) -> list[dict[str, Any]]:
        return self._parts

    def append_text(self, content: str) -> None:
        if not content:
            return
        self._tokens.append(content)
        self._tokens_since_flush += 1
        if self._parts and self._parts[-1].get("type") == "text":
            self._parts[-1]["content"] = str(self._parts[-1].get("content", "")) + content
            return
        self._parts.append({"id": f"text-{uuid4().hex}", "type": "text", "content": content})

    def upsert_tool(self, tool: dict[str, Any]) -> None:
        tool_id = str(tool.get("id") or tool.get("tool_call_id") or uuid4().hex)
        normalized = {
            "id": tool_id,
            "type": "tool",
            "tool": {
                "id": tool_id,
                "name": str(tool.get("name") or tool.get("tool") or "tool"),
                "status": str(tool.get("status") or "running"),
                "summary": str(tool.get("summary") or ""),
            },
        }
        for index, part in enumerate(self._parts):
            if part.get("type") == "tool" and (part.get("tool") or {}).get("id") == tool_id:
                existing_tool = dict(part.get("tool") or {})
                self._parts[index] = {
                    **part,
                    "tool": {**existing_tool, **normalized["tool"]},
                }
                return
        self._parts.append(normalized)

    def flush(self, *, status: str = "running", force: bool = False) -> None:
        content = self.content
        parts_json = json.dumps(self._parts, ensure_ascii=False, default=str)
        should_flush = (
            force
            or self._tokens_since_flush >= self._min_tokens_between_flushes
            or time.monotonic() - self._last_flush_at >= self._max_seconds_between_flushes
            or status != self._flushed_status
        )
        if not should_flush:
            return

        already_flushed = (
            content == self._flushed_content
            and parts_json == self._flushed_parts_json
            and status == self._flushed_status
        )
        if already_flushed:
            self._mark_flushed()
            return

        self._store.update_message(
            self._message.id,
            content=content,
            metadata={
                "source": "run",
                "run_id": self._run_id,
                "status": status,
                "parts": self._parts,
            },
        )
        self._flushed_content = content
        self._flushed_parts_json = parts_json
        self._flushed_status = status
        self._mark_flushed()

    def _mark_flushed(self) -> None:
        self._tokens_since_flush = 0
        self._last_flush_at = time.monotonic()
