from __future__ import annotations

from dataclasses import replace

from .types import BudgetAccounting, Section

DEFAULT_MAX_CHARS = 24000

SECTION_BUDGETS: dict[str, int] = {
    "runtime": 900,
    "session_summary": 1600,
    "soul": 5000,
    "user": 2400,
    "dreams": 1800,
    "curated_memory": 3600,
    "retrieved_memory": 2200,
    "context_pact": 2200,
    "skill_index": 1200,
    "selected_skills": 3600,
    "extracted_context": 1600,
    "session_metadata": 1600,
    "working_directory": 600,
    "tool_use": 2200,
    "memory_boundary": 900,
    "plan": 1200,
    "critic_feedback": 1400,
    "subagent_summary": 1800,
}

SECTION_MIN_CHARS: dict[str, int] = {
    "runtime": 200,
    "soul": 800,
    "user": 200,
    "dreams": 200,
    "memory_boundary": 200,
    "tool_use": 400,
}

REQUIRED_SECTIONS: frozenset[str] = frozenset({"runtime", "soul", "memory_boundary", "tool_use"})


def _truncate_to(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def allocate_sections(
    drafts: list[Section],
    *,
    max_chars: int,
) -> tuple[list[Section], BudgetAccounting]:
    non_empty = [draft for draft in drafts if draft.content]
    section_caps: dict[str, int] = {}
    section_grants: dict[str, int] = {}

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
            content = _truncate_to(content, cap)
            truncated = True
        capped.append(replace(draft, content=content, truncated=truncated))

    active = [section for section in capped if not section.dropped]
    requested = sum(len(section.content) for section in active)
    if requested <= max_chars:
        for section in active:
            section_grants[section.name] = section_caps[section.name]
        return finalize_sections(capped, section_caps, section_grants, requested, max_chars)

    remaining = max_chars
    grants: dict[str, int] = {}
    required_sections = [section for section in active if section.required]
    optional_sections = [section for section in active if not section.required]

    for section in required_sections:
        floor = min(section.min_chars, len(section.content))
        grants[section.name] = min(floor, remaining)
        remaining = max(0, remaining - grants[section.name])

    if any(grants[s.name] < s.min_chars for s in required_sections) and remaining == 0:
        total_floor = sum(grants[s.name] for s in required_sections)
        if total_floor > max_chars and total_floor > 0:
            scale = max_chars / total_floor
            for section in required_sections:
                grants[section.name] = max(1, int(grants[section.name] * scale))

    optional_sections.sort(key=lambda s: (-s.priority, s.render_order, s.name))
    optional_sizes = {section.name: len(section.content) for section in optional_sections}
    optional_total = sum(optional_sizes.values())

    if optional_total > 0 and remaining > 0:
        tentative: dict[str, int] = {}
        for section in optional_sections:
            share = int(remaining * optional_sizes[section.name] / optional_total)
            tentative[section.name] = min(share, section.budget_chars, len(section.content))
        slack = remaining - sum(tentative.values())
        if slack > 0:
            for section in optional_sections:
                cap = min(section.budget_chars, len(section.content))
                take = min(cap - tentative[section.name], slack)
                if take <= 0:
                    continue
                tentative[section.name] += take
                slack -= take
                if slack <= 0:
                    break
        grants.update(tentative)
    else:
        for section in optional_sections:
            grants[section.name] = 0

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
            content = _truncate_to(content, grant)
            truncated = True
        finalized.append(replace(section, content=content, truncated=truncated))
        section_grants[section.name] = grant

    return finalize_sections(finalized, section_caps, section_grants, requested, max_chars)


def finalize_sections(
    sections: list[Section],
    section_caps: dict[str, int],
    section_grants: dict[str, int],
    requested: int,
    max_chars: int,
) -> tuple[list[Section], BudgetAccounting]:
    ordered = sorted(sections, key=lambda s: (s.render_order, -s.priority, s.name))
    kept = [section for section in ordered if not section.dropped and section.content]
    accounting = BudgetAccounting(
        requested_chars=requested,
        granted_chars=sum(len(section.content) for section in kept),
        max_chars=max_chars,
        section_count=len(kept),
        truncated_count=sum(1 for section in kept if section.truncated),
        dropped_count=sum(1 for section in ordered if section.dropped),
        section_caps=section_caps,
        section_grants=section_grants,
    )
    return ordered, accounting
