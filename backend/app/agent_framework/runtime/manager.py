from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from langchain_core.messages import HumanMessage

from ..agent import RunStopped
from ..observability import RunMetricsRecorder
from ..prompt_context import merge_context_pact
from ..storage import PostgresAgentStore, get_agent_store, utc_now
from .attachments import _attachment_store
from .compaction import compact_transcript_records, should_compact
from .event_service import RunEventService
from .events import AgentEvent, cancelled_event, done_event, error_event, map_stream_part
from .graph_runtime import GraphRuntime
from .message_writer import AssistantMessageWriter
from .run_inputs import (
    build_history_messages,
    build_user_message_content,
    extract_memory_request,
)
from .types import RunCreatePayload
from .verification import TaskVerifier

logger = logging.getLogger(__name__)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _snapshot_skill_activation(snapshot: dict[str, Any]) -> dict[str, Any]:
    metadata = snapshot.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    activation = metadata.get("skill_activation")
    return activation if isinstance(activation, dict) else {}


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    return [str(value)] if str(value) else []


class RunManager:
    def __init__(
        self,
        store: PostgresAgentStore | None = None,
        *,
        graph_factory: Callable[[], Awaitable[Any]] | None = None,
        graph_runtime: GraphRuntime | None = None,
        verifier: Any | None = None,
        max_verification_attempts: int | None = None,
    ) -> None:
        self.store = store or get_agent_store()
        self._graph_runtime = graph_runtime or GraphRuntime(graph_factory=graph_factory)
        self._events = RunEventService(store=self.store)
        self._verifier = verifier or TaskVerifier()
        self._max_verification_attempts = (
            max_verification_attempts
            if max_verification_attempts is not None
            else self._default_max_verification_attempts()
        )
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
        if payload.idempotency_key:
            existing = self.store.find_run_by_idempotency_key(
                payload.session_id,
                payload.idempotency_key,
            )
            if existing is not None:
                return existing
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
            idempotency_key=payload.idempotency_key,
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

        if not payload.skip_user_persist:
            self.store.append_message(
                payload.session_id,
                role="user",
                content=payload.message,
                metadata={
                    "source": "run",
                    "run_id": run_id,
                    "frontend": payload.metadata.get("frontend_settings"),
                    "attachments": payload.attachments,
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
            payload={"content": payload.message, "assistant_message_id": assistant_message.id},
        )

        assistant_writer = AssistantMessageWriter(
            store=self.store,
            message=assistant_message,
            run_id=run_id,
        )
        metrics = RunMetricsRecorder(
            self.store,
            session_id=payload.session_id,
            run_id=run_id,
            agent_id=payload.agent_id,
        )
        metrics.start()
        metrics.tick_turn()
        metrics.record_prompt_chars(len(payload.message))

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
            self._finalize_run_metrics(
                metrics,
                status="cancelled",
                terminal_reason="cancelled",
                assistant_writer=assistant_writer,
            )

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

            history_messages = build_history_messages(
                self.store,
                payload,
                attachment_store=_attachment_store,
            )
            inputs = {
                "session_id": payload.session_id,
                "agent_id": payload.agent_id,
                "metadata": {**payload.metadata, "run_id": run_id},
                "messages": [
                    *history_messages,
                    HumanMessage(
                        content=build_user_message_content(
                            payload.message,
                            payload.attachments,
                            attachment_store=_attachment_store,
                        )
                    ),
                ],
            }
            pending_approval_seen = False
            changed_files_seen = False
            await self.append_and_publish_event(
                payload.session_id,
                run_id,
                AgentEvent(type="model_start", data={"agent_id": payload.agent_id}),
            )
            async for part in self._graph_runtime.stream(payload.session_id, inputs):
                self._record_model_usage(metrics, part)
                event = map_stream_part(part)
                if event is None:
                    continue
                published = False
                if event.type == "token":
                    token = str(event.data.get("content", ""))
                    assistant_writer.append_text(token)
                    await self.append_and_publish_event(payload.session_id, run_id, event)
                    published = True
                    await asyncio.sleep(0)
                    assistant_writer.flush()
                elif event.type == "reasoning":
                    reasoning_content = str(event.data.get("content", ""))
                    if reasoning_content:
                        assistant_writer.append_reasoning(reasoning_content)
                    await self.append_and_publish_event(payload.session_id, run_id, event)
                    published = True
                    await asyncio.sleep(0)
                    assistant_writer.flush()
                elif event.type == "tool_start":
                    tool_call_id = str(
                        event.data.get("tool_call_id") or event.data.get("run_id") or "tool"
                    )
                    tool_name = str(event.data.get("tool", "tool"))
                    if tool_name in {"write_local_file", "run_shell_command"}:
                        changed_files_seen = True
                    args = (
                        event.data.get("args") if isinstance(event.data.get("args"), dict) else {}
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
                    await self.append_and_publish_event(payload.session_id, run_id, event)
                    published = True
                    await asyncio.sleep(0)
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
                    raw_status = str(event.data.get("status", "ok"))
                    if raw_status == "pending_approval":
                        pending_approval_seen = True
                    metrics.record_tool(error=raw_status == "error")
                    status = (
                        "running"
                        if raw_status == "pending_approval"
                        else "error"
                        if raw_status == "error"
                        else "done"
                    )
                    result = str(event.data.get("content") or event.data.get("output") or "")
                    assistant_writer.upsert_tool(
                        {
                            "id": tool_call_id,
                            "tool": event.data.get("tool", "tool"),
                            "status": raw_status if raw_status == "pending_approval" else status,
                            "summary": result,
                        }
                    )
                    await self.append_and_publish_event(payload.session_id, run_id, event)
                    published = True
                    await asyncio.sleep(0)
                    assistant_writer.flush(force=True)
                    self.store.upsert_tool_call(
                        payload.session_id,
                        run_id=run_id,
                        tool_call_id=tool_call_id,
                        name=str(event.data.get("tool", "tool")),
                        status=status,
                        result=result,
                    )
                if not published:
                    await self.append_and_publish_event(payload.session_id, run_id, event)
                if await cancel_if_requested():
                    return

            if await cancel_if_requested():
                return

            if pending_approval_seen:
                assistant_writer.flush(status="waiting_approval", force=True)
                self.store.update_run_status(run_id, status="interrupted", finished_at=utc_now())
                self.store.finish_run(
                    payload.session_id,
                    run_id=run_id,
                    status="stopped",
                    reason="等待用户审批",
                )
                await self.append_and_publish_event(payload.session_id, run_id, done_event())
                self._finalize_run_metrics(
                    metrics,
                    status="interrupted",
                    terminal_reason="waiting_approval",
                    assistant_writer=assistant_writer,
                )
                return

            await self._emit_memory_recall_trace(payload.session_id, run_id)
            await self.append_and_publish_event(
                payload.session_id,
                run_id,
                AgentEvent(
                    type="model_end",
                    data={
                        "model": metrics.model,
                        "prompt_tokens": metrics.prompt_tokens,
                        "completion_tokens": metrics.completion_tokens,
                        "reasoning_tokens": metrics.reasoning_tokens,
                        "total_tokens": metrics.total_tokens,
                        "finish_reason": metrics.finish_reason,
                    },
                ),
            )
            verification_summary = await self._maybe_verify_task(
                payload,
                run_id,
                changed_files_seen=changed_files_seen,
                assistant_writer=assistant_writer,
                inputs=inputs,
            )
            if verification_summary is not None:
                assistant_writer.append_text(
                    "\n\n验证摘要："
                    f"{verification_summary.summary}"
                )
            assistant_writer.flush(status="completed", force=True)
            self.store.update_run_status(run_id, status="completed", finished_at=utc_now())
            self.store.finish_run(payload.session_id, run_id=run_id, status="completed")
            await self.append_and_publish_event(payload.session_id, run_id, done_event())
            self._finalize_run_metrics(
                metrics,
                status="completed",
                terminal_reason="completed",
                assistant_writer=assistant_writer,
            )
        except RunStopped:
            await finish_cancelled()
        except asyncio.CancelledError:
            status = "cancelled" if self.store.is_run_cancel_requested(run_id) else "interrupted"
            event = (
                cancelled_event("运行已取消")
                if status == "cancelled"
                else AgentEvent(
                    type="interrupted",
                    data={"status": "interrupted", "reason": "运行已中断"},
                )
            )
            assistant_writer.flush(status=status, force=True)
            self.store.update_run_status(run_id, status=status, finished_at=utc_now())
            self.store.finish_run(payload.session_id, run_id=run_id, status="stopped")
            await self.append_and_publish_event(payload.session_id, run_id, event)
            self._finalize_run_metrics(
                metrics,
                status=status,
                terminal_reason=status,
                assistant_writer=assistant_writer,
            )
            if status == "interrupted":
                raise
        except Exception as exc:  # noqa: BLE001 - run errors are persisted and streamed.
            event = error_event(exc)
            metrics.record_error()
            await self.append_and_publish_event(
                payload.session_id,
                run_id,
                AgentEvent(type="model_error", data={"message": str(exc)}),
            )
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
            self._finalize_run_metrics(
                metrics,
                status="error",
                terminal_reason="error",
                assistant_writer=assistant_writer,
            )

    async def stream_run_events(
        self,
        run_id: str,
        after_sequence: int | None = None,
    ) -> AsyncIterator[AgentEvent]:
        try:
            async for event in self._events.stream_run_events(
                run_id,
                after_sequence=after_sequence,
            ):
                yield event
        finally:
            await self.flush_pending_deltas(run_id)

    async def flush_pending_deltas(self, run_id: str) -> None:
        run = self.store.get_run(run_id)
        if run is None:
            return
        await self._events.flush_deltas(str(run["session_id"]), run_id, force=True)

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

    async def _emit_memory_recall_trace(self, session_id: str, run_id: str) -> None:
        list_snapshots = getattr(self.store, "list_prompt_snapshots", None)
        list_injections = getattr(self.store, "list_memory_injections_for_snapshot", None)
        if list_snapshots is None or list_injections is None:
            return
        try:
            snapshots = list_snapshots(run_id=run_id, limit=1)
            if not snapshots:
                return
            injections = list_injections(str(snapshots[0]["id"]))
        except Exception:  # noqa: BLE001 - trace enrichment must not break a run.
            return
        if not injections:
            return
        await self.append_and_publish_event(
            session_id,
            run_id,
            AgentEvent(
                type="memory_recall",
                data={
                    "snapshot_id": snapshots[0]["id"],
                    "memory_count": len(injections),
                    "memories": injections,
                },
            ),
        )

    def _record_model_usage(self, metrics: RunMetricsRecorder, part: tuple[str, Any]) -> None:
        if not isinstance(part, tuple) or len(part) != 2:
            return
        part_type, data = part
        if part_type != "messages" or not isinstance(data, tuple) or not data:
            return
        chunk = data[0]
        usage = getattr(chunk, "usage_metadata", None)
        response = getattr(chunk, "response_metadata", None)
        if not isinstance(usage, dict) and not isinstance(response, dict):
            return
        response_data = response if isinstance(response, dict) else {}
        usage_data = usage if isinstance(usage, dict) else {}
        token_usage = response_data.get("token_usage")
        if isinstance(token_usage, dict):
            usage_data = {**token_usage, **usage_data}
        metrics.record_token_usage(
            prompt_tokens=_optional_int(
                usage_data.get("input_tokens")
                or usage_data.get("prompt_tokens")
                or usage_data.get("prompt_token_count")
            ),
            completion_tokens=_optional_int(
                usage_data.get("output_tokens")
                or usage_data.get("completion_tokens")
                or usage_data.get("completion_token_count")
            ),
            total_tokens=_optional_int(usage_data.get("total_tokens")),
            reasoning_tokens=_optional_int(
                usage_data.get("reasoning_tokens") or usage_data.get("reasoning_token_count")
            ),
            model=(
                str(response_data.get("model_name") or response_data.get("model") or "")
                or None
            ),
            finish_reason=(
                str(response_data.get("finish_reason") or response_data.get("stop_reason") or "")
                or None
            ),
        )

    def _finalize_run_metrics(
        self,
        metrics: RunMetricsRecorder,
        *,
        status: str,
        terminal_reason: str,
        assistant_writer: AssistantMessageWriter,
    ) -> dict[str, Any] | None:
        if metrics.finalized:
            return None
        row = metrics.finalize(
            status=status,
            terminal_reason=terminal_reason,
            output_chars=len(assistant_writer.content),
        )
        self._record_skill_activation_feedback(
            metrics,
            status=status,
            terminal_reason=terminal_reason,
            metrics_row=row,
        )
        return row

    def _record_skill_activation_feedback(
        self,
        metrics: RunMetricsRecorder,
        *,
        status: str,
        terminal_reason: str,
        metrics_row: dict[str, Any] | None,
    ) -> None:
        list_snapshots = getattr(self.store, "list_prompt_snapshots", None)
        list_tool_calls = getattr(self.store, "list_tool_calls_for_run", None)
        record_trace = getattr(self.store, "record_skill_activation_trace", None)
        catalog = getattr(self.store, "skill_catalog", None)
        if list_snapshots is None or list_tool_calls is None or record_trace is None:
            return
        try:
            snapshots = list_snapshots(run_id=metrics.run_id, limit=50)
            tool_calls = list_tool_calls(metrics.run_id)
        except Exception:  # noqa: BLE001 - feedback traces must not break run finalization.
            return

        successful_tools = {
            str(call.get("name"))
            for call in tool_calls
            if str(call.get("status") or "").lower() in {"done", "ok"}
            and str(call.get("name") or "")
        }
        latency_ms = float((metrics_row or {}).get("duration_ms") or 0.0)
        can_credit = status in {"completed", "error"}
        credited_skill_ids = self._credited_skill_ids(metrics.run_id)

        for snapshot in snapshots:
            activation = _snapshot_skill_activation(snapshot)
            selected = activation.get("selected")
            if not isinstance(selected, list):
                continue
            for item in selected:
                if not isinstance(item, dict):
                    continue
                skill_id = str(item.get("skill_id") or item.get("id") or "").strip()
                if not skill_id:
                    continue
                required_tools = _string_list(item.get("required_tools"))
                matched_tools = sorted(set(required_tools) & successful_tools)
                creditable = can_credit and bool(required_tools) and bool(matched_tools)
                credited = creditable and skill_id not in credited_skill_ids
                try:
                    _trace, created = record_trace(
                        session_id=metrics.session_id,
                        run_id=metrics.run_id,
                        snapshot_id=str(snapshot["id"]),
                        skill_id=skill_id,
                        skill_name=str(item.get("name") or ""),
                        relative_path=str(item.get("relative_path") or ""),
                        required_tools=required_tools,
                        matched_tools=matched_tools,
                        credited=credited,
                        terminal_status=status,
                        terminal_reason=terminal_reason,
                        selected=item,
                    )
                except Exception:  # noqa: BLE001 - best-effort feedback only.
                    continue
                if credited and created and catalog is not None:
                    credited_skill_ids.add(skill_id)
                    try:
                        catalog.record_invocation(
                            skill_id,
                            success=status == "completed",
                            latency_ms=latency_ms,
                        )
                    except Exception:  # noqa: BLE001 - trace is the durable source of truth.
                        continue

    def _credited_skill_ids(self, run_id: str) -> set[str]:
        list_traces = getattr(self.store, "list_skill_activation_traces_for_run", None)
        if list_traces is None:
            return set()
        try:
            traces = list_traces(run_id)
        except Exception:  # noqa: BLE001 - run feedback is best-effort.
            return set()
        return {str(trace.get("skill_id")) for trace in traces if trace.get("credited")}

    async def _maybe_verify_task(
        self,
        payload: RunCreatePayload,
        run_id: str,
        *,
        changed_files_seen: bool,
        assistant_writer: AssistantMessageWriter,
        inputs: dict[str, Any],
    ) -> Any | None:
        if not self._verifier.should_verify(payload, changed_files_seen=changed_files_seen):
            return None
        last_summary = None
        for attempt in range(1, self._max_verification_attempts + 1):
            await self.append_and_publish_event(
                payload.session_id,
                run_id,
                AgentEvent(
                    type="verification_start",
                    data={
                        "attempt": attempt,
                        "max_attempts": self._max_verification_attempts,
                    },
                ),
            )
            summary = await self._verifier.verify(
                payload=payload,
                run_id=run_id,
                max_attempts=1,
            )
            last_summary = summary
            end_payload = {
                **summary.as_dict(),
                "attempt": attempt,
                "max_attempts": self._max_verification_attempts,
            }
            await self.append_and_publish_event(
                payload.session_id,
                run_id,
                AgentEvent(type="verification_end", data=end_payload),
            )
            if summary.status != "failed" or attempt >= self._max_verification_attempts:
                return summary
            await self._run_verification_fix_pass(
                payload,
                run_id,
                assistant_writer=assistant_writer,
                inputs=inputs,
                verification_summary=summary.summary,
            )
        return last_summary

    async def _run_verification_fix_pass(
        self,
        payload: RunCreatePayload,
        run_id: str,
        *,
        assistant_writer: AssistantMessageWriter,
        inputs: dict[str, Any],
        verification_summary: str,
    ) -> None:
        fix_inputs = {
            **inputs,
            "messages": [
                *list(inputs.get("messages") or []),
                HumanMessage(
                    content=(
                        "Verification failed. Fix the implementation, then provide a concise "
                        f"update. Verification summary: {verification_summary}"
                    )
                ),
            ],
        }
        async for part in self._graph_runtime.stream(payload.session_id, fix_inputs):
            event = map_stream_part(part)
            if event is None:
                continue
            if event.type == "token":
                assistant_writer.append_text(str(event.data.get("content", "")))
                await self.append_and_publish_event(payload.session_id, run_id, event)
                await asyncio.sleep(0)
                assistant_writer.flush()
                continue
            if event.type == "reasoning":
                reasoning_content = str(event.data.get("content", ""))
                if reasoning_content:
                    assistant_writer.append_reasoning(reasoning_content)
                await self.append_and_publish_event(payload.session_id, run_id, event)
                await asyncio.sleep(0)
                assistant_writer.flush()
                continue
            await self.append_and_publish_event(payload.session_id, run_id, event)

    def _default_max_verification_attempts(self) -> int:
        raw = os.getenv("TOMMY_MAX_VERIFICATION_ATTEMPTS", "2")
        try:
            return max(1, min(5, int(raw)))
        except ValueError:
            return 2

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
            from ..memory_platform import get_default_memory_provider

            provider = get_default_memory_provider(self.store)
            embedding = provider.embedder.embed(memory_candidate)
            if embedding:
                self.store.memories.update_embedding(
                    proposal["id"],
                    embedding=embedding,
                    model=provider.embedder.model,
                )
        except Exception as exc:  # noqa: BLE001 - embedding is best-effort
            logger.debug("Unable to embed proposed memory %s: %s", proposal.get("id"), exc)
        await self.append_and_publish_event(
            payload.session_id,
            run_id,
            AgentEvent(
                type="memory_write",
                data={
                    "status": "proposed",
                    "proposal": proposal,
                    "message": "已生成记忆提案，确认后才会写入长期记忆。",
                },
            ),
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
            int(recent_compactions[0].get("message_count") or 0) if recent_compactions else 0
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
            from ..memory_platform import get_default_memory_provider

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
        except Exception as exc:  # noqa: BLE001 - never fail compaction on flush errors
            logger.warning("Unable to flush memories before compaction for run %s: %s", run_id, exc)

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
        return build_history_messages(
            self.store,
            payload,
            attachment_store=_attachment_store,
        )

    def _event_from_stored_event(self, row: dict[str, Any]) -> AgentEvent:
        return self._events.event_from_stored_event(row)
