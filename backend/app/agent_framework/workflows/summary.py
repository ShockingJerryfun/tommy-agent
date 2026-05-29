"""Bounded workflow summaries."""

from __future__ import annotations


def workflow_summary_markdown(
    *,
    workflow_name: str,
    status: str,
    phase_outputs: dict[str, list[str]],
    max_chars: int = 1800,
) -> str:
    lines = [
        f"## Workflow Results: {workflow_name}",
        f"- Status: {status}",
    ]
    for phase_id, outputs in phase_outputs.items():
        lines.append(f"- Phase `{phase_id}` outputs: {len(outputs)}")
        for output in outputs[:5]:
            if output:
                lines.append(f"  - {output}")
    return _truncate("\n".join(lines), max_chars)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
