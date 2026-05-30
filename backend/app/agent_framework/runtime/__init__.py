from __future__ import annotations

from .attachments import MAX_ATTACHMENT_BYTES, AttachmentStore
from .background_tasks import BackgroundRunHandle, BackgroundRunQueue, CancellationToken
from .compaction import (
    CompactionResult,
    compact_messages,
    compact_transcript_records,
    should_compact,
)
from .event_bridge import EventBridge
from .event_bus import EventBus
from .event_service import RunEventService
from .events import (
    AgentEvent,
    cancelled_event,
    done_event,
    error_event,
    format_sse,
    map_langgraph_event,
    map_stream_part,
    stopped_event,
)
from .graph_runtime import GraphRuntime
from .health import runtime_health
from .message_writer import AssistantMessageWriter
from .run_steps import TERMINAL_EVENT_TYPES, TERMINAL_RUN_STATUSES, event_to_run_step
from .types import AttachmentRef, RunCreatePayload
from .verification import TaskVerifier, VerificationAttempt, VerificationSummary

MessageWriter = AssistantMessageWriter

__all__ = [
    "AgentEvent",
    "AssistantMessageWriter",
    "AttachmentStore",
    "AttachmentRef",
    "cancelled_event",
    "BackgroundRunHandle",
    "BackgroundRunQueue",
    "CancellationToken",
    "compact_messages",
    "compact_transcript_records",
    "CompactionResult",
    "done_event",
    "error_event",
    "EventBus",
    "EventBridge",
    "format_sse",
    "GraphRuntime",
    "map_langgraph_event",
    "map_stream_part",
    "MAX_ATTACHMENT_BYTES",
    "MessageWriter",
    "RunCreatePayload",
    "RunManager",
    "RunEventService",
    "should_compact",
    "stopped_event",
    "TERMINAL_EVENT_TYPES",
    "TERMINAL_RUN_STATUSES",
    "TaskVerifier",
    "VerificationAttempt",
    "VerificationSummary",
    "event_to_run_step",
    "runtime_health",
]


def __getattr__(name: str) -> object:
    if name == "RunManager":
        from .manager import RunManager

        return RunManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
