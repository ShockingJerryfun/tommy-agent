from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from ..storage.interfaces import EventStore, RunStore
from .events import AgentEvent, done_event, error_event
from .run_steps import TERMINAL_EVENT_TYPES, TERMINAL_RUN_STATUSES, event_to_run_step


@dataclass
class _PendingDelta:
    event_type: str
    content: str


@dataclass
class _RunDeltaBuffer:
    items: list[_PendingDelta] = field(default_factory=list)
    char_count: int = 0
    last_flush_at: float = field(default_factory=time.monotonic)


class RunEventService:
    """Streams high-frequency live events separately from durable run events."""

    def __init__(
        self,
        *,
        store: EventStore | RunStore,
        max_transient_events_per_run: int = 512,
        delta_flush_chars: int = 768,
        delta_flush_seconds: float = 0.4,
    ) -> None:
        self._store = store
        self._max_transient_events_per_run = max_transient_events_per_run
        self._delta_flush_chars = max(1, int(delta_flush_chars))
        self._delta_flush_seconds = max(0.0, float(delta_flush_seconds))
        self._subscribers: dict[str, set[asyncio.Queue[AgentEvent]]] = {}
        self._transient_events: dict[str, list[AgentEvent]] = {}
        self._delta_buffers: dict[str, _RunDeltaBuffer] = {}
        self._lock = asyncio.Lock()

    async def append_and_publish(
        self,
        session_id: str,
        run_id: str,
        event: AgentEvent,
    ) -> dict[str, Any] | None:
        event_with_run = AgentEvent(
            type=event.type,
            data={**event.data, "run_id": run_id},
        )
        if event_with_run.type in {"token", "reasoning"}:
            await self.publish_event(run_id, event_with_run, transient=True)
            await self.append_delta(
                session_id,
                run_id,
                kind="reasoning" if event_with_run.type == "reasoning" else "message",
                content=str(event_with_run.data.get("content") or ""),
            )
            return None

        if event_with_run.type not in {"message_delta", "reasoning_delta"}:
            await self.flush_deltas(session_id, run_id, force=True)

        step_type, label, status = event_to_run_step(event_with_run)
        stored = self._store.append_run_event(
            session_id,
            run_id=run_id,
            type=step_type,
            label=label,
            status=status,
            payload={
                **event_with_run.data,
                "agent_event": event_with_run.model_dump(mode="json"),
            },
        )
        await self.publish_event(
            run_id,
            AgentEvent(
                type=event_with_run.type,
                data={**event_with_run.data, "sequence": stored["sequence"]},
            ),
        )
        if event_with_run.type in TERMINAL_EVENT_TYPES:
            async with self._lock:
                self._transient_events.pop(run_id, None)
                self._delta_buffers.pop(run_id, None)
        return stored

    async def append_delta(
        self,
        session_id: str,
        run_id: str,
        *,
        kind: str,
        content: str,
    ) -> list[dict[str, Any]]:
        if not content:
            return []
        event_type = "reasoning_delta" if kind == "reasoning" else "message_delta"
        should_flush = False
        async with self._lock:
            buffer = self._delta_buffers.setdefault(run_id, _RunDeltaBuffer())
            buffer.items.append(_PendingDelta(event_type=event_type, content=content))
            buffer.char_count += len(content)
            age = time.monotonic() - buffer.last_flush_at
            should_flush = (
                buffer.char_count >= self._delta_flush_chars
                or age >= self._delta_flush_seconds
            )
        if should_flush:
            return await self.flush_deltas(session_id, run_id)
        return []

    async def flush_deltas(
        self,
        session_id: str,
        run_id: str,
        *,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        async with self._lock:
            buffer = self._delta_buffers.get(run_id)
            if buffer is None or not buffer.items:
                return []
            if not force:
                age = time.monotonic() - buffer.last_flush_at
                if (
                    buffer.char_count < self._delta_flush_chars
                    and age < self._delta_flush_seconds
                ):
                    return []
            items = buffer.items
            self._delta_buffers[run_id] = _RunDeltaBuffer(last_flush_at=time.monotonic())

        stored_events: list[dict[str, Any]] = []
        for event_type, content in self._coalesce_delta_items(items):
            agent_event = AgentEvent(
                type=event_type,  # type: ignore[arg-type]
                data={
                    "run_id": run_id,
                    "content": content,
                    "char_count": len(content),
                },
            )
            stored = self._store.append_run_event(
                session_id,
                run_id=run_id,
                type=event_type,
                label="消息增量" if event_type == "message_delta" else "推理增量",
                status="done",
                payload={
                    "run_id": run_id,
                    "content": content,
                    "char_count": len(content),
                    "agent_event": agent_event.model_dump(mode="json"),
                },
            )
            stored_events.append(stored)
        return stored_events

    @staticmethod
    def _coalesce_delta_items(items: list[_PendingDelta]) -> list[tuple[str, str]]:
        coalesced: list[tuple[str, str]] = []
        for item in items:
            if not item.content:
                continue
            if coalesced and coalesced[-1][0] == item.event_type:
                event_type, content = coalesced[-1]
                coalesced[-1] = (event_type, content + item.content)
            else:
                coalesced.append((item.event_type, item.content))
        return coalesced

    async def publish_event(
        self,
        run_id: str,
        event: AgentEvent,
        *,
        transient: bool = False,
    ) -> None:
        async with self._lock:
            if transient:
                events = [*self._transient_events.get(run_id, []), event]
                self._transient_events[run_id] = events[-self._max_transient_events_per_run :]
            queues = list(self._subscribers.get(run_id, set()))
        for queue in queues:
            queue.put_nowait(event)

    async def stream_run_events(
        self,
        run_id: str,
        after_sequence: int | None = None,
    ) -> AsyncIterator[AgentEvent]:
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        async with self._lock:
            self._subscribers.setdefault(run_id, set()).add(queue)
        last_sequence = after_sequence
        try:
            history = self._store.list_run_events_after(
                run_id,
                after_sequence=after_sequence,
                limit=1000,
            )
            for row in history:
                event = self.event_from_stored_event(row)
                last_sequence = int(row["sequence"])
                yield event
                if event.type in TERMINAL_EVENT_TYPES:
                    return

            run = self._store.get_run(run_id)
            if run and run["status"] in TERMINAL_RUN_STATUSES:
                return

            async with self._lock:
                buffered = list(self._transient_events.get(run_id, []))
            for event in buffered:
                yield event

            while True:
                event = await queue.get()
                sequence = event.data.get("sequence")
                if isinstance(sequence, int) and last_sequence is not None:
                    if sequence <= last_sequence:
                        continue
                if isinstance(sequence, int):
                    last_sequence = sequence
                yield event
                if event.type in TERMINAL_EVENT_TYPES:
                    return
        finally:
            async with self._lock:
                subscribers = self._subscribers.get(run_id)
                if subscribers is not None:
                    subscribers.discard(queue)
                    if not subscribers:
                        self._subscribers.pop(run_id, None)

    def event_from_stored_event(self, row: dict[str, Any]) -> AgentEvent:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        agent_event = payload.get("agent_event") if isinstance(payload, dict) else None
        if isinstance(agent_event, dict) and isinstance(agent_event.get("type"), str):
            data = agent_event.get("data") if isinstance(agent_event.get("data"), dict) else {}
            return AgentEvent(
                type=agent_event["type"],
                data={
                    **data,
                    "run_id": row.get("run_id"),
                    "sequence": row.get("sequence"),
                },
            )
        if row.get("type") == "error":
            return error_event(str(payload.get("message") or row.get("label") or "Unknown error"))
        if row.get("type") == "done":
            return done_event()
        return AgentEvent(
            type="node_end",
            data={
                "run_id": row.get("run_id"),
                "sequence": row.get("sequence"),
                "label": row.get("label"),
                "stored_type": row.get("type"),
            },
        )
