"""ContextBuilder v2 — deterministic, budget-aware prompt assembly.

The builder emits a :class:`RenderedContext` containing:

1. A list of :class:`Section` objects, sorted by an explicit ``render_order``
   so the prompt layout is deterministic regardless of the order they were
   produced in.
2. A :class:`BudgetAccounting` describing how the global character budget
   was distributed across sections (and which sections were truncated or
   dropped).
3. A list of injected memories with audit-friendly metadata.

The builder also knows how to persist a *prompt snapshot* (the assembled
sections plus a content hash) and the corresponding ``memory_injections``
through ``ContextBuilder.persist_snapshot``. ``messages_with_context`` in
``prompts.py`` calls into this, so every model invocation leaves a
reproducible audit trail.

Public surface kept stable for backward compatibility:

- ``ContextSection`` is now an alias of ``Section``.
- ``RenderedContext.snapshot()`` returns the same shape as before plus a
  ``budget`` field; consumers that ignore unknown fields keep working.
- ``ContextBuilder.SECTION_BUDGETS`` is preserved verbatim.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .context import pact_markdown
from .paths import DATA_ROOT
from .skills import SkillCatalog
from .state import AgentState
from .storage import get_agent_store


@dataclass(frozen=True)
class Section:
    """A single rendered prompt section.

    ``render_order`` controls layout. ``priority`` controls which sections
    survive when the global budget is exhausted (higher = keep). ``required``
    means the section is always emitted; the allocator must give it at
    least ``min_chars`` even if other sections must be dropped to make room.
    """

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


# Back-compat alias so existing imports keep working.
ContextSection = Section


@dataclass(frozen=True)
class BudgetAccounting:
    """How the allocator distributed the global budget for this build."""

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


# Default global cap for the assembled system prompt. Roughly ~30k tokens
# at 4 chars/token, well under any DeepSeek context window. Override by
# passing ``max_chars`` on :class:`ContextBuildRequest` or via state metadata.
DEFAULT_MAX_CHARS = 24000

# Render groups define the deterministic top-down prompt layout. Sections
# inside a group are sorted by ``priority`` desc, then ``name`` for stable
# ordering. The group ordering is intentionally fixed and not data-driven.
_RENDER_ORDER: dict[str, int] = {
    "runtime": 10,
    "soul": 20,
    "user": 30,
    "memory_boundary": 40,
    "tool_use": 50,
    "context_pact": 60,
    "session_summary": 70,
    "session_metadata": 75,
    "working_directory": 78,
    "curated_memory": 80,
    "retrieved_memory": 85,
    "skills": 90,
    "extracted_context": 95,
    "plan": 32,
    "critic_feedback": 36,
    "subagent_summary": 88,
}


class ContextBuilder:
    """Builds a bounded, deterministic system prompt for each graph turn."""

    # Per-section hard cap (chars). The allocator may grant *less* but never
    # more than this. Numbers chosen to keep the assembled prompt stable
    # against the previous behavior; tuned later by the eval harness.
    SECTION_BUDGETS: dict[str, int] = {
        "runtime": 900,
        "session_summary": 1600,
        "soul": 5000,
        "user": 2400,
        "curated_memory": 3600,
        "retrieved_memory": 2200,
        "context_pact": 2200,
        "skills": 2200,
        "extracted_context": 1600,
        "session_metadata": 1600,
        "working_directory": 600,
        "tool_use": 2200,
        "memory_boundary": 900,
        "plan": 1200,
        "critic_feedback": 1400,
        "subagent_summary": 1800,
    }

    # Per-section floor (chars). Required sections that cannot be granted
    # this minimum survive at this size; non-required sections are dropped
    # entirely instead of being emitted below their floor.
    SECTION_MIN_CHARS: dict[str, int] = {
        "runtime": 200,
        "soul": 800,
        "user": 200,
        "memory_boundary": 200,
        "tool_use": 400,
    }

    REQUIRED_SECTIONS: frozenset[str] = frozenset(
        {"runtime", "soul", "memory_boundary", "tool_use"}
    )

    def __init__(
        self,
        store: Any | None = None,
        *,
        memory_provider: Any | None = None,
    ) -> None:
        self.store = store or get_agent_store()
        self._memory_provider = memory_provider

    @property
    def memory_provider(self) -> Any:
        """Lazy-bind a default :class:`MemoryProvider` against ``self.store``.

        We resolve lazily so importing this module doesn't pay the cost
        of constructing the embedder/reranker (which may try to load
        heavy deps in production setups).
        """

        if self._memory_provider is None:
            from .memory_platform import get_default_memory_provider

            self._memory_provider = get_default_memory_provider(self.store)
        return self._memory_provider

    # ------------------------------------------------------------------ build

    def build(self, request: ContextBuildRequest) -> RenderedContext:
        state = request.state
        agent_id = str(state.get("agent_id", "default"))
        agent_root = DATA_ROOT / agent_id
        metadata = state.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        frontend_settings = (
            metadata.get("frontend_settings")
            if isinstance(metadata.get("frontend_settings"), dict)
            else {}
        )
        working_directory = (
            str(frontend_settings.get("workingDirectory") or "").strip()
            if isinstance(frontend_settings, dict)
            else ""
        )
        session_id = str(state.get("session_id") or "")
        session = self.store.get_session(session_id) if session_id else None
        context_pact = (
            self.store.get_context_pact(session_id, agent_id=agent_id)
            if session_id
            else {}
        )
        skills = SkillCatalog(agent_id=agent_id, store=self.store).list_skills()
        last_user_message = self._last_user_message(state)
        recalled_memories = self._recall_memories(
            agent_id=agent_id,
            query=last_user_message,
        )

        drafts = self._build_section_drafts(
            agent_root=agent_root,
            session_id=session_id,
            session=session,
            metadata=metadata,
            working_directory=working_directory,
            context_pact=context_pact,
            skills=skills,
            recalled_memories=recalled_memories,
            extracted_context=state.get("extracted_context") or {},
            plan=state.get("plan") or {},
            critic_directives=state.get("critic_directives") or [],
        )

        max_chars = self._resolve_max_chars(request, metadata)
        # The body assembled from the kept sections includes per-section
        # headers (``# title\n\n``) and ``\n\n`` joiners between sections.
        # Subtract an upper-bound estimate so the granted content + overhead
        # together stay under ``max_chars``. Estimating with all non-empty
        # drafts is conservative — if some sections drop, we simply leave
        # slack instead of over-spending.
        overhead_estimate = sum(
            len(f"# {draft.title}\n\n") for draft in drafts if draft.content
        )
        non_empty_count = sum(1 for draft in drafts if draft.content)
        overhead_estimate += max(0, non_empty_count - 1) * 2
        content_budget = max(0, max_chars - overhead_estimate)
        sections, accounting = self._allocate(drafts, max_chars=content_budget)
        accounting = replace(
            accounting,
            max_chars=max_chars,
        )
        rendered = [section for section in sections if not section.dropped and section.content]
        body = "\n\n".join(section.rendered for section in rendered)
        sha = hashlib.sha256(body.encode("utf-8")).hexdigest()

        return RenderedContext(
            content=body,
            sections=rendered,
            injected_memories=[
                self._memory_snapshot(item, query=last_user_message, rank=index)
                for index, item in enumerate(recalled_memories)
            ],
            budget=accounting,
            content_sha256=sha,
        )

    # --------------------------------------------------------- snapshot write

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
        """Write the snapshot + memory injections.

        Returns the snapshot row on success or ``None`` when the call could
        not be persisted (no session id, store missing the new tables, etc.).
        Persistence errors are swallowed so prompt assembly never blocks a
        run on an audit-only failure.
        """

        if not session_id:
            return None
        record = getattr(self.store, "record_prompt_snapshot", None)
        if record is None:
            return None

        sections_payload = [section.snapshot() for section in rendered.sections]
        injections_payload = [
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
                sections=sections_payload,
                budget=rendered.budget.as_dict(),
                metadata=metadata,
                injections=injections_payload,
            )
        except Exception:  # noqa: BLE001 — audit must never break the turn
            return None

    # ---------------------------------------------------------------- helpers

    def _resolve_max_chars(
        self,
        request: ContextBuildRequest,
        metadata: dict[str, Any],
    ) -> int:
        if request.max_chars is not None and request.max_chars > 0:
            return int(request.max_chars)
        meta_cap = metadata.get("context_max_chars")
        if isinstance(meta_cap, int) and meta_cap > 0:
            return meta_cap
        return DEFAULT_MAX_CHARS

    def _build_section_drafts(
        self,
        *,
        agent_root: Path,
        session_id: str,
        session: dict[str, Any] | None,
        metadata: dict[str, Any],
        working_directory: str,
        context_pact: dict[str, Any],
        skills: list[Any],
        recalled_memories: list[dict[str, Any]],
        extracted_context: Any,
        plan: dict[str, Any] | None = None,
        critic_directives: list[dict[str, Any]] | None = None,
    ) -> list[Section]:
        runtime_body = "\n".join(
            [
                "You are running inside a LangGraph-first agent framework.",
                f"Current UTC time: {datetime.now(UTC).isoformat()}",
                f"Session ID: {session_id or 'unknown'}",
            ]
        )
        skills_body = (
            "\n".join(
                f"- {skill.name}: {skill.description or skill.path}" for skill in skills
            )
            or "No installed skills."
        )
        tool_use_body = "\n\n".join(
            [
                (
                    "Use tools when they materially improve the answer. If a tool fails, "
                    "inspect the error and retry with corrected arguments when appropriate."
                ),
                (
                    "Use web_search for current external facts, documentation, "
                    "news, prices, or claims that need citation. Prefer small "
                    "max_results, fast search_depth, "
                    "no raw content, and targeted domains/time ranges to save context."
                ),
                (
                    "When a working directory is selected, treat it as the default project "
                    "scope for conversation context, file tools, and shell commands. "
                    "Do not "
                    "read, write, or run commands outside it unless the user explicitly "
                    "changes the working directory."
                ),
                (
                    "Local file tools may read, list, and write files under the active "
                    "working directory or configured local file access root. "
                    "Use exact paths "
                    "and avoid unnecessary edits."
                ),
            ]
        )
        memory_boundary_body = (
            "Do not claim you have permanently remembered something unless the runtime "
            "reports a confirmed memory write. If the user asks you to remember something, "
            "acknowledge that it has been proposed for confirmation."
        )

        return [
            self._make_section(
                "runtime",
                "Runtime",
                runtime_body,
                source="runtime",
                priority=100,
            ),
            self._make_section(
                "soul",
                "SOUL",
                self._read_optional(agent_root / "SOUL.md"),
                source=str(agent_root / "SOUL.md"),
                priority=95,
            ),
            self._make_section(
                "user",
                "USER",
                self._read_optional(agent_root / "USER.md"),
                source=str(agent_root / "USER.md"),
                priority=85,
            ),
            self._make_section(
                "memory_boundary",
                "Memory Boundary",
                memory_boundary_body,
                source="runtime.memory_policy",
                priority=95,
            ),
            self._make_section(
                "tool_use",
                "Tool Use",
                tool_use_body,
                source="runtime.tool_policy",
                priority=90,
            ),
            self._make_section(
                "context_pact",
                "Context Pact",
                pact_markdown(context_pact),
                source="postgres.context_pacts",
                priority=70,
            ),
            self._make_section(
                "session_summary",
                "Session Summary",
                str((session or {}).get("summary") or "No summary yet."),
                source="postgres.sessions.summary",
                priority=90,
            ),
            self._make_section(
                "session_metadata",
                "Session Metadata",
                str(metadata or {}),
                source="run.metadata",
                priority=50,
            ),
            self._make_section(
                "working_directory",
                "Working Directory",
                working_directory
                or (
                    "No working directory selected. "
                    "Use the configured workspace root when tools need files."
                ),
                source="frontend.settings.workingDirectory",
                priority=70,
            ),
            self._make_section(
                "curated_memory",
                "MEMORY",
                self._read_optional(agent_root / "MEMORY.md"),
                source=str(agent_root / "MEMORY.md"),
                priority=80,
            ),
            self._make_section(
                "retrieved_memory",
                "Active Memory Recall",
                self._memory_markdown(recalled_memories),
                source="postgres.memories.search",
                priority=75,
            ),
            self._make_section(
                "skills",
                "Installed Skills",
                skills_body,
                source="skills.catalog",
                priority=65,
            ),
            self._make_section(
                "extracted_context",
                "Extracted Context",
                str(extracted_context or {}),
                source="graph.state.extracted_context",
                priority=55,
            ),
            self._make_section(
                "plan",
                "Current Plan",
                self._plan_markdown(plan or {}),
                source="graph.state.plan",
                priority=85,
            ),
            self._make_section(
                "critic_feedback",
                "Critic Feedback",
                self._critic_feedback_markdown(critic_directives or []),
                source="graph.state.critic_directives",
                priority=92,
            ),
            self._make_section(
                "subagent_summary",
                "Subagent Results",
                self._subagent_summary_markdown(session_id),
                source="store.subagent_runs",
                priority=70,
            ),
        ]

    def _subagent_summary_markdown(self, session_id: str) -> str:
        if not session_id:
            return ""
        try:
            from .subagents import subagent_summary_section
        except Exception:  # noqa: BLE001 — subagents are optional in tests.
            return ""
        try:
            return subagent_summary_section(self.store, parent_session_id=session_id)
        except Exception:  # noqa: BLE001 — never fail context assembly on this.
            return ""

    def _plan_markdown(self, plan: dict[str, Any]) -> str:
        steps = plan.get("steps") if isinstance(plan, dict) else None
        if not steps:
            return ""
        summary = str(plan.get("summary") or "").strip()
        lines = []
        if summary:
            lines.append(f"Goal: {summary}")
        for index, step in enumerate(steps, start=1):
            lines.append(f"{index}. {step}")
        return "\n".join(lines)

    def _critic_feedback_markdown(self, directives: list[dict[str, Any]]) -> str:
        if not directives:
            return ""
        # Only the most recent directives matter; cap to last 4 to keep the
        # section bounded irrespective of run length.
        recent = directives[-4:]
        lines = []
        for directive in recent:
            kind = str(directive.get("kind") or "note").upper()
            message = str(directive.get("message") or "").strip()
            if message:
                lines.append(f"- [{kind}] {message}")
        return "\n".join(lines)

    def _make_section(
        self,
        name: str,
        title: str,
        content: str,
        *,
        source: str,
        priority: int,
    ) -> Section:
        normalized = str(content or "").strip()
        budget = self.SECTION_BUDGETS.get(name, 1200)
        min_chars = min(self.SECTION_MIN_CHARS.get(name, 0), budget)
        return Section(
            name=name,
            title=title,
            content=normalized,
            source=source,
            priority=priority,
            render_order=_RENDER_ORDER.get(name, 1000),
            budget_chars=budget,
            min_chars=min_chars,
            required=name in self.REQUIRED_SECTIONS,
            original_chars=len(normalized),
        )

    # -------------------------------------------------------------- allocator

    def _allocate(
        self,
        drafts: list[Section],
        *,
        max_chars: int,
    ) -> tuple[list[Section], BudgetAccounting]:
        """Allocate the global ``max_chars`` budget across ``drafts``.

        Algorithm:

        1. Drop empty sections immediately.
        2. Drop the section's overhead-adjusted natural length to its
           per-section cap.
        3. If the sum still fits in ``max_chars``, accept everything.
        4. Otherwise: guarantee ``min_chars`` for every required section
           first; then distribute the remaining budget across the rest in
           priority-then-render-order order, capping each section at its
           per-section cap. Any section whose grant falls below its
           ``min_chars`` (and is not required) is dropped.

        The accounting is returned alongside the resulting sections so the
        snapshot writer can persist *why* the prompt looks the way it does.
        """

        non_empty = [draft for draft in drafts if draft.content]
        section_caps: dict[str, int] = {}
        section_grants: dict[str, int] = {}

        # Apply per-section hard caps before any global trimming.
        capped: list[Section] = []
        for draft in non_empty:
            cap = max(0, draft.budget_chars)
            section_caps[draft.name] = cap
            if cap == 0:
                section_grants[draft.name] = 0
                capped.append(replace(draft, dropped=True, content=""))
                continue
            content = draft.content
            truncated = False
            if len(content) > cap:
                content = content[: cap - 1].rstrip() + "…"
                truncated = True
            capped.append(replace(draft, content=content, truncated=truncated))

        active = [section for section in capped if not section.dropped]
        natural_total = sum(len(section.content) for section in active)
        requested = natural_total

        if natural_total <= max_chars:
            for section in active:
                section_grants[section.name] = section_caps[section.name]
            return self._finalize(capped, section_caps, section_grants, requested, max_chars)

        # We need to shrink. Build the grant map from scratch: required
        # sections first (at min_chars), then everything else proportionally.
        remaining = max_chars
        grants: dict[str, int] = {}
        # Process required first.
        required_sections = [section for section in active if section.required]
        optional_sections = [section for section in active if not section.required]

        for section in required_sections:
            floor = min(section.min_chars, len(section.content))
            grants[section.name] = min(floor, remaining)
            remaining = max(0, remaining - grants[section.name])

        # If even the required floors blew the budget, the requireds get
        # truncated proportionally to fit.
        if any(grants[s.name] < s.min_chars for s in required_sections) and remaining == 0:
            total_floor = sum(grants[s.name] for s in required_sections)
            if total_floor > max_chars and total_floor > 0:
                scale = max_chars / total_floor
                for section in required_sections:
                    grants[section.name] = max(1, int(grants[section.name] * scale))

        # Distribute remainder over optional sections by priority desc, then
        # render_order asc, then name asc — fully deterministic.
        optional_sections.sort(key=lambda s: (-s.priority, s.render_order, s.name))
        optional_sizes = {s.name: len(s.content) for s in optional_sections}
        optional_total = sum(optional_sizes.values())

        if optional_total > 0 and remaining > 0:
            # Proportional split, then clamp at per-section cap and re-spread leftovers.
            tentative: dict[str, int] = {}
            for section in optional_sections:
                share = int(remaining * optional_sizes[section.name] / optional_total)
                tentative[section.name] = min(share, section.budget_chars, len(section.content))
            allocated = sum(tentative.values())
            slack = remaining - allocated
            # Re-spread slack over sections that still have headroom.
            if slack > 0:
                for section in optional_sections:
                    cap = min(section.budget_chars, len(section.content))
                    headroom = cap - tentative[section.name]
                    if headroom <= 0:
                        continue
                    take = min(headroom, slack)
                    tentative[section.name] += take
                    slack -= take
                    if slack <= 0:
                        break
            for section in optional_sections:
                grants[section.name] = tentative[section.name]
        else:
            for section in optional_sections:
                grants[section.name] = 0

        # Fill in missing keys (sections that were already 0-grant).
        for section in active:
            grants.setdefault(section.name, 0)

        # Drop optional sections whose grant fell below their min_chars.
        finalized: list[Section] = []
        for section in capped:
            if section.dropped:
                finalized.append(section)
                continue
            grant = grants.get(section.name, 0)
            if not section.required and grant < max(1, section.min_chars):
                grants[section.name] = 0
                finalized.append(replace(section, dropped=True, content=""))
                continue
            content = section.content
            truncated = section.truncated
            if grant < len(content):
                content = content[: max(0, grant - 1)].rstrip() + "…"
                truncated = True
            finalized.append(replace(section, content=content, truncated=truncated))
            section_grants[section.name] = grant

        return self._finalize(finalized, section_caps, section_grants, requested, max_chars)

    @staticmethod
    def _finalize(
        sections: list[Section],
        section_caps: dict[str, int],
        section_grants: dict[str, int],
        requested: int,
        max_chars: int,
    ) -> tuple[list[Section], BudgetAccounting]:
        # Deterministic render: render_order asc, then priority desc, then name.
        ordered = sorted(
            sections,
            key=lambda s: (s.render_order, -s.priority, s.name),
        )
        kept = [s for s in ordered if not s.dropped and s.content]
        granted = sum(len(s.content) for s in kept)
        accounting = BudgetAccounting(
            requested_chars=requested,
            granted_chars=granted,
            max_chars=max_chars,
            section_count=len(kept),
            truncated_count=sum(1 for s in kept if s.truncated),
            dropped_count=sum(1 for s in ordered if s.dropped),
            section_caps=section_caps,
            section_grants=section_grants,
        )
        return ordered, accounting

    # ----------------------------------------------------------- helpers (io)

    def _last_user_message(self, state: AgentState) -> str:
        for message in reversed(state.get("messages", [])):
            if getattr(message, "type", "") == "human":
                return str(getattr(message, "content", ""))
        return ""

    def _memory_markdown(self, memories: list[dict[str, Any]]) -> str:
        if not memories:
            return "No recalled memories."
        return "\n".join(f"- {item.get('content', '')}" for item in memories)

    def _memory_snapshot(
        self,
        item: dict[str, Any],
        *,
        query: str,
        rank: int,
    ) -> dict[str, Any]:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        return {
            "memory_id": item.get("id"),
            "id": item.get("id"),
            "status": item.get("status"),
            "source_session_id": item.get("source_session_id"),
            "char_count": len(str(item.get("content") or "")),
            "rank": rank,
            "score": item.get("score") or item.get("final_score"),
            "rrf_score": item.get("rrf_score"),
            "fts_rank": item.get("fts_rank"),
            "vector_score": item.get("vector_score"),
            "rerank_score": item.get("rerank_score"),
            "query": query,
            "metadata": metadata,
        }

    def _recall_memories(
        self,
        *,
        agent_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Hybrid retrieval through :class:`MemoryProvider`, with a graceful
        ILIKE fallback if the provider is unavailable for any reason.

        Each item is normalised to the dict shape consumed by
        ``_memory_markdown`` and ``_memory_snapshot``.
        """

        if not query:
            return []
        provider = None
        try:
            provider = self.memory_provider
        except Exception:  # noqa: BLE001 - retrieval must never fail prompt assembly
            provider = None
        if provider is not None:
            try:
                candidates = provider.retrieve_for_context(
                    query, agent_id=agent_id, top_k=top_k
                )
                return [
                    {
                        "id": c.id,
                        "content": c.content,
                        "status": c.status,
                        "source_session_id": c.source_session_id,
                        "metadata": c.metadata,
                        "score": c.final_score,
                        "final_score": c.final_score,
                        "rrf_score": c.rrf_score,
                        "fts_rank": c.fts_rank,
                        "vector_score": c.vector_score,
                        "rerank_score": c.rerank_score,
                    }
                    for c in candidates
                ]
            except Exception:  # noqa: BLE001 - fall back to legacy ILIKE
                pass
        return self.store.search_memories(
            agent_id=agent_id, query=query, limit=top_k
        )

    def _read_optional(self, path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()
