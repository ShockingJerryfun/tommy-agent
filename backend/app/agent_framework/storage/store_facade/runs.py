from __future__ import annotations

from typing import Any


class RunStoreMixin:
    def append_run_event(
        self,
        session_id: str,
        *,
        run_id: str,
        type: str,
        label: str,
        status: str = "done",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.events.append_run_event(
            session_id,
            run_id=run_id,
            type=type,
            label=label,
            status=status,
            payload=payload,
        )

    def list_run_events(self, session_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        return self.events.list_run_events(session_id, limit=limit)

    def list_run_events_after(
        self,
        run_id: str,
        *,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.events.list_run_events_after(run_id, after_sequence=after_sequence, limit=limit)

    def create_run(
        self,
        *,
        session_id: str,
        agent_id: str = "default",
        input: str,
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
        status: str = "queued",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self.runs.create_run(
            session_id=session_id,
            agent_id=agent_id,
            input=input,
            metadata=metadata,
            run_id=run_id,
            status=status,
            idempotency_key=idempotency_key,
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.runs.get_run(run_id)

    def find_run_by_idempotency_key(
        self,
        session_id: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        return self.runs.find_by_idempotency_key(session_id, idempotency_key)

    def update_run_status(self, run_id: str, **updates: Any) -> dict[str, Any] | None:
        return self.runs.update_run_status(run_id, **updates)

    def request_run_cancel(self, run_id: str) -> dict[str, Any] | None:
        return self.runs.request_run_cancel(run_id)

    def is_run_cancel_requested(self, run_id: str) -> bool:
        return self.runs.is_run_cancel_requested(run_id)

    def list_runs(self, session_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        return self.runs.list_runs(session_id, limit=limit)

    def get_run_metrics(self, *, session_id: str, run_id: str) -> dict[str, Any] | None:
        return self.run_metrics.get(session_id=session_id, run_id=run_id)

    def list_run_metrics(self, session_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        return self.run_metrics.list_for_session(session_id, limit=limit)

    def get_latest_run(self, session_id: str) -> dict[str, Any] | None:
        return self.runs.get_latest_run(session_id)

    def get_active_run(self, session_id: str) -> dict[str, Any] | None:
        return self.runs.get_active_run(session_id)

    def list_active_runs(
        self,
        *,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.runs.list_active_runs(session_id=session_id, limit=limit)

    def list_inflight_runs(
        self,
        *,
        session_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        return self.runs.list_inflight_runs(session_id=session_id, limit=limit)

    def finalize_run_as_interrupted(
        self,
        run_id: str,
        *,
        reason: str = "服务进程重启或连接断开后，运行已中断。",
    ) -> dict[str, Any] | None:
        return self.runs.finalize_run_as_interrupted(run_id, reason=reason)

    def start_run(self, session_id: str, *, run_id: str) -> dict[str, Any]:
        return self.run_controls.start_run(session_id, run_id=run_id)

    def request_run_stop(
        self,
        session_id: str,
        *,
        run_id: str | None = None,
        reason: str = "Stopped by user",
    ) -> list[dict[str, Any]]:
        return self.run_controls.request_run_stop(session_id, run_id=run_id, reason=reason)

    def run_stop_requested(self, *, session_id: str, run_id: str) -> bool:
        return self.run_controls.run_stop_requested(session_id=session_id, run_id=run_id)

    def finish_run(
        self,
        session_id: str,
        *,
        run_id: str,
        status: str,
        reason: str = "",
    ) -> dict[str, Any] | None:
        return self.run_controls.finish_run(session_id, run_id=run_id, status=status, reason=reason)

    def upsert_tool_call(
        self,
        session_id: str,
        *,
        run_id: str,
        tool_call_id: str,
        name: str,
        status: str,
        args: dict[str, Any] | None = None,
        result: str | None = None,
    ) -> None:
        self.tool_calls.upsert_tool_call(
            session_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            name=name,
            status=status,
            args=args,
            result=result,
        )

    def list_tool_calls(self, session_id: str) -> list[dict[str, Any]]:
        return self.tool_calls.list_tool_calls(session_id)

    def list_tool_calls_for_run(self, run_id: str) -> list[dict[str, Any]]:
        return self.tool_calls.list_for_run(run_id)

    def record_skill_activation_trace(
        self,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], bool]:
        return self.skill_activation_traces.record_trace(**kwargs)

    def list_skill_activation_traces_for_run(self, run_id: str) -> list[dict[str, Any]]:
        return self.skill_activation_traces.list_for_run(run_id)
