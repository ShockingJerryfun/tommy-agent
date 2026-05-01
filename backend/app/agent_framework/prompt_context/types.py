from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..state import AgentState


@dataclass(frozen=True)
class Section:
    name: str
    title: str
    content: str
    source: str
    priority: int
    render_order: int
    budget_chars: int
    min_chars: int = 0
    required: bool = False
    truncated: bool = False
    dropped: bool = False
    original_chars: int = 0

    @property
    def rendered(self) -> str:
        return f"# {self.title}\n\n{self.content}".strip()

    def snapshot(self, *, preview_chars: int = 360) -> dict[str, Any]:
        preview = self.content[:preview_chars].rstrip()
        if len(self.content) > preview_chars:
            preview = f"{preview}..."
        return {
            "name": self.name,
            "title": self.title,
            "source": self.source,
            "priority": self.priority,
            "render_order": self.render_order,
            "budget_chars": self.budget_chars,
            "min_chars": self.min_chars,
            "required": self.required,
            "char_count": len(self.content),
            "original_chars": self.original_chars,
            "truncated": self.truncated,
            "dropped": self.dropped,
            "preview": preview,
        }


ContextSection = Section


@dataclass(frozen=True)
class BudgetAccounting:
    requested_chars: int
    granted_chars: int
    max_chars: int
    section_count: int
    truncated_count: int
    dropped_count: int
    section_caps: dict[str, int] = field(default_factory=dict)
    section_grants: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested_chars": self.requested_chars,
            "granted_chars": self.granted_chars,
            "max_chars": self.max_chars,
            "section_count": self.section_count,
            "truncated_count": self.truncated_count,
            "dropped_count": self.dropped_count,
            "section_caps": dict(self.section_caps),
            "section_grants": dict(self.section_grants),
        }


@dataclass(frozen=True)
class RenderedContext:
    content: str
    sections: list[Section]
    injected_memories: list[dict[str, Any]]
    budget: BudgetAccounting
    content_sha256: str

    def snapshot(self) -> dict[str, Any]:
        return {
            "section_count": len(self.sections),
            "total_chars": len(self.content),
            "content_sha256": self.content_sha256,
            "sections": [section.snapshot() for section in self.sections],
            "injected_memories": self.injected_memories,
            "budget": self.budget.as_dict(),
        }


@dataclass(frozen=True)
class ContextBuildRequest:
    state: AgentState
    max_chars: int | None = None
