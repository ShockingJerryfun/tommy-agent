from __future__ import annotations

from typing import Any, Protocol

StoreRecord = dict[str, Any]


class MessageRecord(Protocol):
    id: str
    session_id: str
    role: str
    content: str
    metadata: dict[str, Any]
    position: int
    created_at: str


class SessionStore(Protocol):
    def create_session(
        self,
        *,
        agent_id: str = "default",
        title: str = "新对话",
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> str: ...

    def ensure_session(
        self,
        session_id: str,
        *,
        agent_id: str = "default",
        title: str = "新对话",
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    def get_session(self, session_id: str) -> StoreRecord | None: ...

    def list_sessions(self, *, agent_id: str = "default") -> list[StoreRecord]: ...

    def delete_session(self, session_id: str) -> None: ...


class MessageStore(Protocol):
    def append_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> MessageRecord: ...

    def update_message(
        self,
        message_id: str,
        *,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MessageRecord | None: ...

    def list_messages(
        self,
        session_id: str,
        *,
        limit: int | None = None,
    ) -> list[MessageRecord]: ...

    def reset_session_content(
        self,
        session_id: str,
        *,
        messages: list[dict[str, Any]] | None = None,
    ) -> None: ...


class RunStore(Protocol):
    def create_run(
        self,
        *,
        session_id: str,
        agent_id: str = "default",
        input: str,
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
        status: str = "queued",
    ) -> StoreRecord: ...

    def get_run(self, run_id: str) -> StoreRecord | None: ...

    def list_runs(self, session_id: str, *, limit: int = 20) -> list[StoreRecord]: ...

    def get_active_run(self, session_id: str) -> StoreRecord | None: ...

    def update_run_status(self, run_id: str, **updates: Any) -> StoreRecord | None: ...

    def request_run_cancel(self, run_id: str) -> StoreRecord | None: ...

    def is_run_cancel_requested(self, run_id: str) -> bool: ...

    def run_stop_requested(self, *, session_id: str, run_id: str) -> bool: ...


class EventStore(Protocol):
    def append_run_event(
        self,
        session_id: str,
        *,
        run_id: str,
        type: str,
        label: str,
        status: str = "done",
        payload: dict[str, Any] | None = None,
    ) -> StoreRecord: ...

    def list_run_events(self, session_id: str, *, limit: int = 200) -> list[StoreRecord]: ...

    def list_run_events_after(
        self,
        run_id: str,
        *,
        after_sequence: int | None = None,
        limit: int = 1000,
    ) -> list[StoreRecord]: ...


class ApprovalStore(Protocol):
    def create_approval_request(
        self,
        *,
        session_id: str,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        args: dict[str, Any] | None = None,
        risk_level: str = "medium",
        summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> StoreRecord: ...

    def get_approval_request(self, approval_id: str) -> StoreRecord | None: ...

    def update_approval_request(
        self,
        approval_id: str,
        *,
        status: str,
        result: str = "",
        error: str = "",
    ) -> StoreRecord | None: ...


class MemoryProposalStore(Protocol):
    def create_memory(
        self,
        *,
        agent_id: str,
        content: str,
        status: str = "proposed",
        source_session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StoreRecord: ...

    def confirm_memory(self, memory_id: str) -> StoreRecord | None: ...

    def search_memories(
        self,
        *,
        agent_id: str,
        query: str,
        limit: int = 5,
    ) -> list[StoreRecord]: ...
