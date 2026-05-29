"""Reducers and prompt budgeting for workflow phases."""

from __future__ import annotations


def join_outputs_for_reduce(outputs: list[str], *, max_chars: int = 6000) -> str:
    joined = "\n\n".join(f"- {output}" for output in outputs if output)
    return truncate_text(joined, max_chars)


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)].rstrip() + "..."
