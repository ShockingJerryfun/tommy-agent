from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CompactionResult:
    summary: str
    recent_tail: list[Any]
    should_flush_memory: bool


def should_compact(messages: list[Any], *, max_messages: int = 80) -> bool:
    return len(messages) > max_messages


def compact_messages(
    messages: list[Any],
    *,
    keep_recent: int = 20,
    metadata: dict[str, Any] | None = None,
) -> CompactionResult:
    """Create a conservative placeholder compaction result without deleting source history."""
    if not messages:
        return CompactionResult(summary="", recent_tail=[], should_flush_memory=False)

    older = messages[:-keep_recent] if len(messages) > keep_recent else []
    tail = messages[-keep_recent:] if len(messages) > keep_recent else messages
    summary = (
        f"Conversation summary placeholder for {len(older)} older messages. "
        "A production compactor should replace this with an LLM-generated summary "
        "that preserves decisions, tool results, identifiers, and open tasks."
    )
    if metadata:
        summary += f" Metadata: {metadata}"

    return CompactionResult(
        summary=summary,
        recent_tail=list(tail),
        should_flush_memory=bool(older),
    )


def compact_transcript_records(
    messages: list[Any],
    *,
    keep_recent: int = 16,
    max_summary_chars: int = 1400,
) -> CompactionResult:
    """Create an extractive session summary while preserving all original records."""

    if not messages:
        return CompactionResult(summary="", recent_tail=[], should_flush_memory=False)

    older = messages[:-keep_recent] if len(messages) > keep_recent else []
    tail = messages[-keep_recent:] if len(messages) > keep_recent else messages
    highlights: list[str] = []
    for message in older[-24:]:
        role = str(getattr(message, "role", "") or getattr(message, "type", "") or "message")
        content = " ".join(str(getattr(message, "content", "")).split())
        if not content:
            continue
        highlights.append(f"{role}: {content[:180]}")
    summary = "\n".join(highlights)[-max_summary_chars:]
    if older and not summary:
        summary = f"{len(older)} older messages were compacted into the session pact."
    return CompactionResult(
        summary=summary,
        recent_tail=list(tail),
        should_flush_memory=bool(older),
    )
