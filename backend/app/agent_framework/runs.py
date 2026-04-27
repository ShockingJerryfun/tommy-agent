from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from .agent import RunStopped
from .compaction import compact_transcript_records, should_compact
from .context import merge_context_pact
from .events import AgentEvent, cancelled_event, done_event, error_event, map_stream_part
from .runtime import (
    AssistantMessageWriter,
    GraphRuntime,
    RunCreatePayload,
    RunEventService,
)
from .storage import get_agent_store
from .store import PostgresAgentStore, utc_now


def extract_memory_request(message: str) -> str | None:
    normalized = message.strip()
    prefixes = ("请记住", "记住", "帮我记住", "remember that", "please remember")
    for prefix in prefixes:
        if normalized.lower().startswith(prefix.lower()):
            return normalized[len(prefix) :].strip(" ：:，,。")
    return None


class RunManager:
    def __init__(
        self,
        store: PostgresAgentStore | None = None,
        *,
        graph_factory: Callable[[], Awaitable[Any]] | None = None,
        graph_runtime: GraphRuntime | None = None,
    ) -> None:
        self.store = store or get_agent_store()
        self._graph_runtime = graph_runtime or GraphRuntime(graph_factory=graph_factory)
        self._events = RunEventService(store=self.store)
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()

    def is_run_executing(self, run_id: str) -> bool:
        return run_id in self._tasks

    async def reconcile_orphan_inflight_runs(self, session_id: str | None = None) -> list[str]:
        """Mark DB runs that are still queued/running but have no in-process task as interrupted."""
        finalized: list[str] = []
        for run in self.store.list_inflight_runs(session_id=session_id):
            rid = str(run["id"])
            if rid in self._tasks:
                continue
            updated = self.store.finalize_run_as_interrupted(
                rid,
                reason="服务进程重启或连接断开后，运行已中断。",
            )
            if updated is not None and updated.get("status") == "interrupted":
                finalized.append(rid)
        return finalized

    async def create_and_start_run(self, payload: RunCreatePayload) -> dict[str, Any]:
        await self.reconcile_orphan_inflight_runs(payload.session_id)
        self.store.ensure_session(payload.session_id, agent_id=payload.agent_id)
        active = self.store.get_active_run(payload.session_id)
        if active and active["id"] in self._tasks:
            self.store.request_run_cancel(str(active["id"]))
        run = self.store.create_run(
            session_id=payload.session_id,
            agent_id=payload.agent_id,
            input=payload.message,
            metadata=payload.metadata,
        )
        async with self._lock:
            if run["id"] not in self._tasks:
                task = asyncio.create_task(self.execute_run(str(run["id"]), payload))
                self._tasks[str(run["id"])] = task
                task.add_done_callback(lambda _: self._tasks.pop(str(run["id"]), None))
        return run

    async def execute_run(self, run_id: str, payload: RunCreatePayload) -> None:
        self.store.ensure_session(payload.session_id, agent_id=payload.agent_id)
        started_at = utc_now()
        self.store.update_run_status(run_id, status="running", started_at=started_at)
        self.store.start_run(payload.session_id, run_id=run_id)

        if payload.reset_thread:
            await self._graph_runtime.reset_thread(payload.session_id)
            self.store.reset_session_content(
                payload.session_id,
                messages=[
                    {"role": item["role"], "content": item["content"]}
                    for item in payload.history
                    if item.get("content")
                ],
            )

        self.store.append_message(
            payload.session_id,
            role="user",
            content=payload.message,
            metadata={
                "source": "run",
                "run_id": run_id,
                "frontend": payload.metadata.get("frontend_settings"),
            },
        )
        assistant_message = self.store.append_message(
            payload.session_id,
            role="assistant",
            content="",
            metadata={"source": "run", "run_id": run_id, "status": "running", "parts": []},
        )
        self.store.update_run_status(run_id, assistant_message_id=assistant_message.id)
        self.store.append_run_event(
            payload.session_id,
            run_id=run_id,
            type="user",
            label="收到输入",
            status="done",
            payload={"content": payload.message},
        )

        assistant_writer = AssistantMessageWriter(
            store=self.store,
            message=assistant_message,
            run_id=run_id,
        )

        async def finish_cancelled(reason: str = "用户已停止本次运行") -> None:
            event = cancelled_event(reason)
            assistant_writer.flush(status="cancelled", force=True)
            self.store.update_run_status(
                run_id,
                status="cancelled",
                finished_at=utc_now(),
            )
            self.store.finish_run(
                payload.session_id,
                run_id=run_id,
                status="stopped",
                reason=reason,
            )
            await self.append_and_publish_event(payload.session_id, run_id, event)

        async def cancel_if_requested() -> bool:
            if not self.store.is_run_cancel_requested(run_id):
                return False
            await finish_cancelled()
            return True

        try:
            if await cancel_if_requested():
                return

            await self._maybe_create_memory_proposal(payload, run_id)
            if await cancel_if_requested():
                return

            await self._maybe_compact_session(payload, run_id)
            if await cancel_if_requested():
                return

            history_messages = self._build_history_messages(payload)
            inputs = {
                "session_id": payload.session_id,
                "agent_id": payload.agent_id,
                "metadata": {**payload.metadata, "run_id": run_id},
                "messages": [*history_messages, HumanMessage(content=payload.message)],
            }
            async for part in self._graph_runtime.stream(payload.session_id, inputs):
                event = map_stream_part(part)
                if event is None:
                    continue
                if event.type == "token":
                    token = str(event.data.get("content", ""))
                    assistant_writer.append_text(token)
                    assistant_writer.flush()
                elif event.type == "tool_start":
                    tool_call_id = str(
                        event.data.get("tool_call_id") or event.data.get("run_id") or "tool"
                    )
                    args = (
                        event.data.get("args")
                        if isinstance(event.data.get("args"), dict)
                        else {}
                    )
                    summary = json.dumps(args, ensure_ascii=False) if args else "正在运行…"
                    assistant_writer.upsert_tool(
                        {
                            "id": tool_call_id,
                            "tool": event.data.get("tool", "tool"),
                            "status": "running",
                            "summary": summary,
                        }
                    )
                    assistant_writer.flush(force=True)
                    self.store.upsert_tool_call(
                        payload.session_id,
                        run_id=run_id,
                        tool_call_id=tool_call_id,
                        name=str(event.data.get("tool", "tool")),
                        status="running",
                        args=args,
                    )
                elif event.type == "tool_end":
                    tool_call_id = str(
                        event.data.get("tool_call_id") or event.data.get("run_id") or "tool"
                    )
                    status = "error" if str(event.data.get("status", "ok")) == "error" else "done"
                    result = str(event.data.get("content") or event.data.get("output") or "")
                    assistant_writer.upsert_tool(
                        {
                            "id": tool_call_id,
                            "tool": event.data.get("tool", "tool"),
                            "status": status,
                            "summary": result,
                        }
                    )
                    assistant_writer.flush(force=True)
                    self.store.upsert_tool_call(
                        payload.session_id,
                        run_id=run_id,
                        tool_call_id=tool_call_id,
                        name=str(event.data.get("tool", "tool")),
                        status=status,
                        result=result,
                    )
                await self.append_and_publish_event(payload.session_id, run_id, event)
                if await cancel_if_requested():
                    return

            if await cancel_if_requested():
                return

            assistant_writer.flush(status="completed", force=True)
            self.store.update_run_status(run_id, status="completed", finished_at=utc_now())
            self.store.finish_run(payload.session_id, run_id=run_id, status="completed")
            await self.append_and_publish_event(payload.session_id, run_id, done_event())
        except RunStopped:
            await finish_cancelled()
        except asyncio.CancelledError:
            status = "cancelled" if self.store.is_run_cancel_requested(run_id) else "interrupted"
            event = cancelled_event("运行已取消") if status == "cancelled" else AgentEvent(
                type="interrupted",
                data={"status": "interrupted", "reason": "运行已中断"},
            )
            assistant_writer.flush(status=status, force=True)
            self.store.update_run_status(run_id, status=status, finished_at=utc_now())
            self.store.finish_run(payload.session_id, run_id=run_id, status="stopped")
            await self.append_and_publish_event(payload.session_id, run_id, event)
            if status == "interrupted":
                raise
        except Exception as exc:  # noqa: BLE001 - run errors are persisted and streamed.
            event = error_event(exc)
            assistant_writer.flush(status="error", force=True)
            self.store.update_run_status(
                run_id,
                status="error",
                finished_at=utc_now(),
                error=str(exc),
            )
            self.store.finish_run(
                payload.session_id,
                run_id=run_id,
                status="error",
                reason=str(exc),
            )
            await self.append_and_publish_event(payload.session_id, run_id, event)
            await self.append_and_publish_event(payload.session_id, run_id, done_event())

    async def stream_run_events(
        self,
        run_id: str,
        after_sequence: int | None = None,
    ) -> AsyncIterator[AgentEvent]:
        async for event in self._events.stream_run_events(run_id, after_sequence=after_sequence):
            yield event

    async def cancel_run(self, run_id: str) -> dict[str, Any] | None:
        run = self.store.request_run_cancel(run_id)
        if run is None:
            return None
        if run["status"] == "queued" and run_id not in self._tasks:
            run = self.store.update_run_status(run_id, status="cancelled", finished_at=utc_now())
            await self.append_and_publish_event(
                str(run["session_id"]),
                run_id,
                cancelled_event("用户已停止本次运行"),
            )
        return run

    async def append_and_publish_event(
        self,
        session_id: str,
        run_id: str,
        event: AgentEvent,
    ) -> dict[str, Any] | None:
        return await self._events.append_and_publish(session_id, run_id, event)

    async def publish_event(self, run_id: str, event: AgentEvent) -> None:
        await self._events.publish_event(run_id, event)

    async def _maybe_create_memory_proposal(
        self,
        payload: RunCreatePayload,
        run_id: str,
    ) -> None:
        memory_candidate = extract_memory_request(payload.message)
        if not memory_candidate:
            return
        proposal = self.store.create_memory(
            agent_id=payload.agent_id,
            content=memory_candidate,
            status="proposed",
            source_session_id=payload.session_id,
            metadata={"source": "explicit_user_request"},
        )
        try:
            from .memory_platform import get_default_memory_provider

            provider = get_default_memory_provider(self.store)
            embedding = provider.embedder.embed(memory_candidate)
            if embedding:
                self.store.memories.update_embedding(
                    proposal["id"],
                    embedding=embedding,
                    model=provider.embedder.model,
                )
        except Exception:  # noqa: BLE001 - embedding is best-effort
            pass
        await self.append_and_publish_event(
            payload.session_id,
            run_id,
            AgentEvent(
                type="memory",
                data={
                    "status": "proposed",
                    "proposal": proposal,
                    "message": "已生成记忆提案，确认后才会写入长期记忆。",
                },
            ),
        )

    async def _maybe_compact_session(self, payload: RunCreatePayload, run_id: str) -> None:
        stored_for_compaction = self.store.list_messages(payload.session_id)
        recent_compactions = self.store.list_compaction_runs(payload.session_id, limit=1)
        last_compacted_count = (
            int(recent_compactions[0].get("message_count") or 0)
            if recent_compactions
            else 0
        )
        should_run_compaction = (
            should_compact(stored_for_compaction, max_messages=48)
            and len(stored_for_compaction) >= last_compacted_count + 12
        )
        if not should_run_compaction:
            return

        # Pre-compaction memory flush. Reflect on the soon-to-be-summarised
        # message tail before compaction rewrites them so user-stated facts
        # become memory proposals instead of being lost in the summary.
        try:
            from .memory_platform import get_default_memory_provider

            keep_recent = 18
            older_for_flush = (
                stored_for_compaction[:-keep_recent]
                if len(stored_for_compaction) > keep_recent
                else []
            )
            if older_for_flush:
                get_default_memory_provider(self.store).on_pre_compact_flush(
                    agent_id=payload.agent_id,
                    session_id=payload.session_id,
                    run_id=run_id,
                    messages=older_for_flush,
                )
        except Exception:  # noqa: BLE001 - never fail compaction on flush errors
            pass

        compaction = compact_transcript_records(stored_for_compaction, keep_recent=18)
        if not compaction.summary:
            return
        self.store.set_session_summary(payload.session_id, compaction.summary)
        current_pact = self.store.get_context_pact(payload.session_id, agent_id=payload.agent_id)
        pact = merge_context_pact(current_pact, {"summary": compaction.summary})
        self.store.upsert_context_pact(payload.session_id, agent_id=payload.agent_id, pact=pact)
        record = self.store.append_compaction_run(
            payload.session_id,
            run_id=run_id,
            summary=compaction.summary,
            message_count=len(stored_for_compaction),
            kept_messages=len(compaction.recent_tail),
            metadata={"trigger": "run_threshold"},
        )
        await self.append_and_publish_event(
            payload.session_id,
            run_id,
            AgentEvent(type="compaction", data={"compaction": record, "pact": pact}),
        )

    def _build_history_messages(self, payload: RunCreatePayload) -> list[Any]:
        if not payload.reset_thread:
            return []

        history_messages = []
        if payload.history:
            for item in payload.history:
                content = item.get("content") or ""
                if not content:
                    continue
                if item.get("role") == "assistant":
                    history_messages.append(AIMessage(content=content))
                else:
                    history_messages.append(HumanMessage(content=content))
            return history_messages

        stored_messages = self.store.list_messages(payload.session_id, limit=24)
        for item in stored_messages:
            if not item.content or item.content == payload.message:
                continue
            if item.role == "assistant":
                history_messages.append(AIMessage(content=item.content))
            elif item.role == "user":
                history_messages.append(HumanMessage(content=item.content))
        return history_messages

    def _event_from_stored_event(self, row: dict[str, Any]) -> AgentEvent:
        return self._events.event_from_stored_event(row)
