from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage

from .agent import RunStopped
from .compaction import compact_transcript_records, should_compact
from .context import merge_context_pact
from .events import AgentEvent, cancelled_event, done_event, error_event, map_stream_part
from .memory import LocalMemoryStore, build_thread_config
from .store import SQLiteAgentStore, utc_now

TERMINAL_EVENT_TYPES = {"done", "error", "cancelled", "interrupted", "stopped"}
TERMINAL_RUN_STATUSES = {"completed", "cancelled", "interrupted", "error"}


@dataclass(frozen=True)
class RunCreatePayload:
    session_id: str
    message: str
    agent_id: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, str]] = field(default_factory=list)
    reset_thread: bool = False


def event_to_run_step(event: AgentEvent) -> tuple[str, str, str]:
    data = event.data
    if event.type == "token":
        return "agent", "Agent 正在生成", "running"
    if event.type == "tool_start":
        return "tool", f"{data.get('tool', '工具')} 运行中", "running"
    if event.type == "tool_end":
        failed = str(data.get("status", "ok")) == "error"
        return (
            "tool",
            f"{data.get('tool', '工具')} {'失败' if failed else '完成'}",
            "error" if failed else "done",
        )
    if event.type == "node_end":
        updates = data.get("updates") if isinstance(data.get("updates"), list) else []
        if "action" in updates:
            return "agent", "工具调用完成", "done"
        if "agent" in updates:
            return "agent", "回复已更新", "done"
        return "agent", "状态已更新", "done"
    if event.type == "error":
        return "error", "请求出错", "error"
    if event.type in {"cancelled", "interrupted", "stopped"}:
        return "agent", "生成已停止", "done"
    if event.type == "done":
        return "done", "完成", "done"
    if event.type == "skill":
        proposal = data.get("proposal") if isinstance(data.get("proposal"), dict) else {}
        label = f"Skill {proposal.get('name') or data.get('name') or 'proposal'}"
        return "skill", label, "done"
    if event.type == "pact":
        return "pact", "上下文 Pact 已更新", "done"
    if event.type == "delegate":
        return "delegate", f"委派给 {data.get('target_agent', 'agent')}", "running"
    if event.type == "compaction":
        return "compaction", "会话已压缩", "done"
    if event.type == "approval_pending":
        approval = data.get("approval") if isinstance(data.get("approval"), dict) else {}
        return "approval", f"等待审批：{approval.get('tool_name', '工具')}", "running"
    if event.type == "approval_resolved":
        approval = data.get("approval") if isinstance(data.get("approval"), dict) else {}
        failed = str(approval.get("status") or "") in {"failed", "rejected"}
        return "approval", "审批已处理", "error" if failed else "done"
    if event.type == "subagent_start":
        return "subagent", f"子 Agent {data.get('target_agent', '')} 启动", "running"
    if event.type == "subagent_end":
        return "subagent", f"子 Agent {data.get('target_agent', '')} 完成", "done"
    return "agent", event.type, "done"


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
        store: SQLiteAgentStore | None = None,
        *,
        graph_factory: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        self.store = store or SQLiteAgentStore()
        self._graph_factory = graph_factory
        self._subscribers: dict[str, set[asyncio.Queue[AgentEvent]]] = {}
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
        memory_store = LocalMemoryStore(agent_id=payload.agent_id)
        memory_store.ensure_layout()
        self.store.ensure_session(payload.session_id, agent_id=payload.agent_id)
        graph = await self._get_graph()
        started_at = utc_now()
        self.store.update_run_status(run_id, status="running", started_at=started_at)
        self.store.start_run(payload.session_id, run_id=run_id)

        if payload.reset_thread:
            try:
                await graph.checkpointer.adelete_thread(payload.session_id)
            except Exception:
                pass
            self.store.reset_session_content(
                payload.session_id,
                messages=[
                    {"role": item["role"], "content": item["content"]}
                    for item in payload.history
                    if item.get("content")
                ],
            )

        memory_store.append_session_event(
            payload.session_id,
            {"role": "user", "content": payload.message},
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

        assistant_tokens: list[str] = []
        assistant_message_parts: list[dict[str, Any]] = []
        tokens_since_flush = 0
        last_flush_at = time.monotonic()
        flushed_content = ""
        flushed_parts_json = "[]"
        flushed_status = "running"

        def append_text_part(content: str) -> None:
            if not content:
                return
            if assistant_message_parts and assistant_message_parts[-1].get("type") == "text":
                assistant_message_parts[-1]["content"] = (
                    str(assistant_message_parts[-1].get("content", "")) + content
                )
                return
            assistant_message_parts.append(
                {"id": f"text-{uuid4().hex}", "type": "text", "content": content}
            )

        def upsert_tool_part(tool: dict[str, Any]) -> None:
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
            for index, part in enumerate(assistant_message_parts):
                if part.get("type") == "tool" and (part.get("tool") or {}).get("id") == tool_id:
                    existing_tool = dict(part.get("tool") or {})
                    assistant_message_parts[index] = {
                        **part,
                        "tool": {**existing_tool, **normalized["tool"]},
                    }
                    return
            assistant_message_parts.append(normalized)

        def flush_assistant_message(*, status: str = "running", force: bool = False) -> None:
            nonlocal flushed_content, flushed_parts_json, flushed_status
            nonlocal last_flush_at, tokens_since_flush

            content = "".join(assistant_tokens)
            parts_json = json.dumps(assistant_message_parts, ensure_ascii=False, default=str)
            should_flush = (
                force
                or tokens_since_flush >= 20
                or time.monotonic() - last_flush_at >= 0.5
                or status != flushed_status
            )
            if not should_flush:
                return
            already_flushed = (
                content == flushed_content
                and parts_json == flushed_parts_json
                and status == flushed_status
            )
            if already_flushed:
                tokens_since_flush = 0
                last_flush_at = time.monotonic()
                return

            self.store.update_message(
                assistant_message.id,
                content=content,
                metadata={
                    "source": "run",
                    "run_id": run_id,
                    "status": status,
                    "parts": assistant_message_parts,
                },
            )
            flushed_content = content
            flushed_parts_json = parts_json
            flushed_status = status
            tokens_since_flush = 0
            last_flush_at = time.monotonic()

        async def finish_cancelled(reason: str = "用户已停止本次运行") -> None:
            event = cancelled_event(reason)
            flush_assistant_message(status="cancelled", force=True)
            assistant_content = "".join(assistant_tokens)
            if assistant_content:
                memory_store.append_session_event(
                    payload.session_id,
                    {"role": "assistant", "status": "cancelled", "content": assistant_content},
                )
            self.store.update_run_status(
                run_id,
                status="cancelled",
                finished_at=utc_now(),
            )
            self.store.finish_run(payload.session_id, run_id=run_id, status="stopped", reason=reason)
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
            config = build_thread_config(payload.session_id)

            async for part in graph.astream(
                inputs,
                config=config,
                stream_mode=["messages", "updates", "custom"],
            ):
                event = map_stream_part(part)
                if event is None:
                    continue
                if event.type == "token":
                    token = str(event.data.get("content", ""))
                    assistant_tokens.append(token)
                    append_text_part(token)
                    tokens_since_flush += 1
                    flush_assistant_message()
                elif event.type == "tool_start":
                    tool_call_id = str(
                        event.data.get("tool_call_id") or event.data.get("run_id") or "tool"
                    )
                    args = event.data.get("args") if isinstance(event.data.get("args"), dict) else {}
                    summary = json.dumps(args, ensure_ascii=False) if args else "正在运行…"
                    upsert_tool_part(
                        {
                            "id": tool_call_id,
                            "tool": event.data.get("tool", "tool"),
                            "status": "running",
                            "summary": summary,
                        }
                    )
                    flush_assistant_message(force=True)
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
                    upsert_tool_part(
                        {
                            "id": tool_call_id,
                            "tool": event.data.get("tool", "tool"),
                            "status": status,
                            "summary": result,
                        }
                    )
                    flush_assistant_message(force=True)
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

            assistant_content = "".join(assistant_tokens)
            flush_assistant_message(status="completed", force=True)
            memory_store.append_session_event(
                payload.session_id,
                {"role": "assistant", "status": "done", "content": assistant_content},
            )
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
            flush_assistant_message(status=status, force=True)
            assistant_content = "".join(assistant_tokens)
            if assistant_content:
                memory_store.append_session_event(
                    payload.session_id,
                    {"role": "assistant", "status": status, "content": assistant_content},
                )
            self.store.update_run_status(run_id, status=status, finished_at=utc_now())
            self.store.finish_run(payload.session_id, run_id=run_id, status="stopped")
            await self.append_and_publish_event(payload.session_id, run_id, event)
            if status == "interrupted":
                raise
        except Exception as exc:  # noqa: BLE001 - run errors are persisted and streamed.
            event = error_event(exc)
            flush_assistant_message(status="error", force=True)
            assistant_content = "".join(assistant_tokens)
            if assistant_content:
                memory_store.append_session_event(
                    payload.session_id,
                    {"role": "assistant", "status": "error", "content": assistant_content},
                )
            self.store.update_run_status(
                run_id,
                status="error",
                finished_at=utc_now(),
                error=str(exc),
            )
            self.store.finish_run(payload.session_id, run_id=run_id, status="error", reason=str(exc))
            await self.append_and_publish_event(payload.session_id, run_id, event)
            await self.append_and_publish_event(payload.session_id, run_id, done_event())

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
            history = self.store.list_run_events_after(
                run_id,
                after_sequence=after_sequence,
                limit=1000,
            )
            for row in history:
                event = self._event_from_stored_event(row)
                last_sequence = int(row["sequence"])
                yield event
                if event.type in TERMINAL_EVENT_TYPES:
                    return

            run = self.store.get_run(run_id)
            if run and run["status"] in TERMINAL_RUN_STATUSES:
                return

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
    ) -> dict[str, Any]:
        event_with_run = AgentEvent(
            type=event.type,
            data={**event.data, "run_id": run_id},
        )
        step_type, label, status = event_to_run_step(event_with_run)
        stored = self.store.append_run_event(
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
        return stored

    async def publish_event(self, run_id: str, event: AgentEvent) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(run_id, set()))
        for queue in queues:
            queue.put_nowait(event)

    async def _get_graph(self) -> Any:
        if self._graph_factory is None:
            from .agent import build_agent_graph
            from .memory import create_async_checkpointer

            return build_agent_graph(
                checkpointer=await create_async_checkpointer(),
                async_model=True,
            )
        return await self._graph_factory()

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
