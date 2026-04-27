"""SubagentSummary — compact rendering of recent subagent results.

The ContextBuilder calls :func:`subagent_summary_section` to inject a
section into the parent agent's prompt summarising what each subagent
returned. Rendering is intentionally cheap: this is the parent's bird's
-eye view, not a full transcript.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..store import PostgresAgentStore


@dataclass(frozen=True)
class SubagentSummary:
    id: str
    role: str
    task: str
    status: str
    score: float
    response_preview: str
    citations_count: int
    child_session_id: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "task": self.task,
            "status": self.status,
            "score": self.score,
            "response_preview": self.response_preview,
            "citations_count": self.citations_count,
            "child_session_id": self.child_session_id,
            "created_at": self.created_at,
        }


def list_recent_summaries(
    store: PostgresAgentStore,
    *,
    parent_session_id: str,
    limit: int = 5,
    preview_chars: int = 320,
) -> list[SubagentSummary]:
    rows = store.subagent_runs.list_for_session(parent_session_id, limit=limit)
    summaries: list[SubagentSummary] = []
    for row in rows:
        text = str(row.get("final_response") or "")
        meta = row.get("metadata") or {}
        summaries.append(
            SubagentSummary(
                id=row["id"],
                role=row["role"],
                task=str(row["task"])[:200],
                status=row["status"],
                score=float(row.get("score") or 0.0),
                response_preview=text[:preview_chars].rstrip()
                + ("…" if len(text) > preview_chars else ""),
                citations_count=int(meta.get("citations_count") or 0),
                child_session_id=row["child_session_id"],
                created_at=row.get("created_at", ""),
            )
        )
    return summaries


def subagent_summary_markdown(summaries: list[SubagentSummary]) -> str:
    """Render summaries as a compact markdown block for the system prompt."""

    if not summaries:
        return ""
    lines: list[str] = []
    for summary in summaries:
        status_marker = "✓" if summary.status == "completed" else summary.status
        header = (
            f"- **{summary.role}** [{status_marker}, score={summary.score:.2f}, "
            f"cites={summary.citations_count}] — task: {summary.task}"
        )
        lines.append(header)
        if summary.response_preview:
            lines.append(f"  > {summary.response_preview}")
    return "\n".join(lines)


def subagent_summary_section(
    store: PostgresAgentStore,
    *,
    parent_session_id: str,
    limit: int = 5,
) -> str:
    """Convenience wrapper used by ContextBuilder integrations."""

    summaries = list_recent_summaries(
        store, parent_session_id=parent_session_id, limit=limit
    )
    return subagent_summary_markdown(summaries)
