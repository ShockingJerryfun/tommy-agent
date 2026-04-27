from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from ..events import AgentEvent, done_event, error_event
from ..storage.interfaces import EventStore, RunStore
from .run_steps import TERMINAL_EVENT_TYPES, TERMINAL_RUN_STATUSES, event_to_run_step


class RunEventService:
    """Streams high-frequency live events separately from durable run events."""

    def __init__(
        self,
        *,
        store: EventStore | RunStore,
        max_transient_events_per_run: int = 512,
    ) -> None:
        self._store = store
        self._max_transient_events_per_run = max_transient_events_per_run
        self._subscribers: dict[str, set[asyncio.Queue[AgentEvent]]] = {}
        self._transient_events: dict[str, list[AgentEvent]] = {}
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
        if event_with_run.type == "token":
            await self.publish_event(run_id, event_with_run, transient=True)
            return None

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
        return stored

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
