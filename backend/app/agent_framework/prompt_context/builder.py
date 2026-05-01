"""Budget-aware system prompt assembly.

The public surface of this module is intentionally small:

- `ContextBuilder` builds and persists prompt context.
- `ContextBuildRequest`, `RenderedContext`, `Section`, and `ContextSection`
  are stable DTOs used by tests and callers.

Implementation details live under `prompt_context/`.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from ..paths import DATA_ROOT
from ..skills_forge.catalog import SkillCatalog
from ..storage import get_agent_store
from .budgets import (
    DEFAULT_MAX_CHARS,
    REQUIRED_SECTIONS,
    SECTION_BUDGETS,
    SECTION_MIN_CHARS,
    allocate_sections,
)
from .memory import last_user_message, memory_snapshot, recall_memories
from .sections import build_section_drafts
from .types import (
    BudgetAccounting,
    ContextBuildRequest,
    ContextSection,
    RenderedContext,
    Section,
)


class ContextBuilder:
    """Builds a bounded, deterministic system prompt for each graph turn."""

    SECTION_BUDGETS = SECTION_BUDGETS
    SECTION_MIN_CHARS = SECTION_MIN_CHARS
    REQUIRED_SECTIONS = REQUIRED_SECTIONS

    def __init__(self, store: Any | None = None, *, memory_provider: Any | None = None) -> None:
        self.store = store or get_agent_store()
        self._memory_provider = memory_provider

    @property
    def memory_provider(self) -> Any:
        if self._memory_provider is None:
            from ..memory_platform import get_default_memory_provider

            self._memory_provider = get_default_memory_provider(self.store)
        return self._memory_provider

    def build(self, request: ContextBuildRequest) -> RenderedContext:
        state = request.state
        agent_id = str(state.get("agent_id", "default"))
        session_id = str(state.get("session_id") or "")
        metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
        frontend_settings = (
            metadata.get("frontend_settings")
            if isinstance(metadata.get("frontend_settings"), dict)
            else {}
        )
        working_directory = str(frontend_settings.get("workingDirectory") or "").strip()
        session = self.store.get_session(session_id) if session_id else None
        context_pact = (
            self.store.get_context_pact(session_id, agent_id=agent_id) if session_id else {}
        )
        query = last_user_message(state)
        memory_provider = self._resolve_memory_provider()
        recalled = recall_memories(
            store=self.store,
            memory_provider=memory_provider,
            agent_id=agent_id,
            query=query,
        )
        drafts = build_section_drafts(
            store=self.store,
            agent_root=DATA_ROOT / agent_id,
            session_id=session_id,
            session=session,
            metadata=metadata,
            working_directory=working_directory,
            context_pact=context_pact,
            skills=SkillCatalog(agent_id=agent_id, store=self.store).list_skills(),
            recalled_memories=recalled,
            extracted_context=state.get("extracted_context") or {},
            current_time=datetime.now(UTC).isoformat(),
            plan=state.get("plan") or {},
            critic_directives=state.get("critic_directives") or [],
        )

        max_chars = self._resolve_max_chars(request, metadata)
        content_budget = max(0, max_chars - self._render_overhead(drafts))
        sections, accounting = allocate_sections(drafts, max_chars=content_budget)
        accounting = replace(accounting, max_chars=max_chars)
        rendered_sections = [
            section for section in sections if not section.dropped and section.content
        ]
        body = "\n\n".join(section.rendered for section in rendered_sections)
        return RenderedContext(
            content=body,
            sections=rendered_sections,
            injected_memories=[
                memory_snapshot(item, query=query, rank=index)
                for index, item in enumerate(recalled)
            ],
            budget=accounting,
            content_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        )

    def persist_snapshot(
        self,
        rendered: RenderedContext,
        *,
        session_id: str,
        agent_id: str,
        run_id: str | None = None,
        model: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not session_id:
            return None
        record = getattr(self.store, "record_prompt_snapshot", None)
        if record is None:
            return None
        injections = [
            {**item, "rank": item.get("rank", index)}
            for index, item in enumerate(rendered.injected_memories)
        ]
        try:
            return record(
                session_id=session_id,
                agent_id=agent_id,
                run_id=run_id,
                model=model,
                total_chars=len(rendered.content),
                section_count=len(rendered.sections),
                truncated_count=rendered.budget.truncated_count,
                dropped_count=rendered.budget.dropped_count,
                content_sha256=rendered.content_sha256,
                sections=[section.snapshot() for section in rendered.sections],
                budget=rendered.budget.as_dict(),
                metadata=metadata,
                injections=injections,
            )
        except Exception:  # noqa: BLE001 - audit persistence must not break a turn.
            return None

    def _resolve_memory_provider(self) -> Any | None:
        try:
            return self.memory_provider
        except Exception:  # noqa: BLE001 - context assembly falls back to text search.
            return None

    def _resolve_max_chars(self, request: ContextBuildRequest, metadata: dict[str, Any]) -> int:
        if request.max_chars is not None and request.max_chars > 0:
            return int(request.max_chars)
        meta_cap = metadata.get("context_max_chars")
        if isinstance(meta_cap, int) and meta_cap > 0:
            return meta_cap
        return DEFAULT_MAX_CHARS

    @staticmethod
    def _render_overhead(drafts: list[Section]) -> int:
        non_empty = [draft for draft in drafts if draft.content]
        headers = sum(len(f"# {draft.title}\n\n") for draft in non_empty)
        joins = max(0, len(non_empty) - 1) * 2
        return headers + joins


__all__ = [
    "BudgetAccounting",
    "ContextBuildRequest",
    "ContextBuilder",
    "ContextSection",
    "RenderedContext",
    "Section",
]
