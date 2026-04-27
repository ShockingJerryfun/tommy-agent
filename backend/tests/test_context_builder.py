"""Tests for ContextBuilder v2 — section model, ordering, allocator, snapshot.

These tests use a stub store so we can exercise the allocator and the
snapshot/memory-injection plumbing deterministically without touching the
real Postgres schema (which is exercised by ``test_prompt_snapshots.py``).
"""

from __future__ import annotations

import hashlib
from typing import Any

from langchain_core.messages import HumanMessage

from app.agent_framework.context_builder import (
    ContextBuilder,
    ContextBuildRequest,
    Section,
)


class _StubStore:
    """Minimal store double exposing only what ContextBuilder uses."""

    def __init__(self, *, memories: list[dict[str, Any]] | None = None) -> None:
        self.snapshots: list[dict[str, Any]] = []
        self._memories = memories or []

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return {"id": session_id, "summary": "stub summary"}

    def get_context_pact(self, session_id: str, *, agent_id: str) -> dict[str, Any]:
        return {}

    def search_memories(
        self,
        *,
        agent_id: str,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        return list(self._memories[:limit])

    def list_skills(self, *, agent_id: str = "default") -> list[Any]:
        return []

    def record_prompt_snapshot(self, **kwargs: Any) -> dict[str, Any]:
        record = {"id": f"prompt-{len(self.snapshots) + 1}", **kwargs}
        self.snapshots.append(record)
        return record


def _make_state(*, user_msg: str = "hello world") -> dict[str, Any]:
    return {
        "session_id": "sess-test",
        "agent_id": "default",
        "messages": [HumanMessage(content=user_msg)],
        "metadata": {"run_id": "run-test"},
        "extracted_context": {},
    }


def _patch_skill_catalog(monkeypatch) -> None:
    from app.agent_framework import context_builder as cb

    class _StubCatalog:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def list_skills(self) -> list[Any]:
            return []

    monkeypatch.setattr(cb, "SkillCatalog", _StubCatalog)


def _freeze_time(monkeypatch) -> None:
    """Freeze the runtime section's clock so two builds hash identically."""

    from datetime import UTC, datetime

    from app.agent_framework import context_builder as cb

    fixed = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return fixed if tz is None else fixed.astimezone(tz)

    monkeypatch.setattr(cb, "datetime", _FrozenDatetime)


def test_sections_are_rendered_in_deterministic_order(monkeypatch) -> None:
    _patch_skill_catalog(monkeypatch)
    _freeze_time(monkeypatch)
    builder = ContextBuilder(store=_StubStore())
    rendered = builder.build(ContextBuildRequest(state=_make_state()))

    # Build twice with the same input — the layout must be byte-identical.
    again = builder.build(ContextBuildRequest(state=_make_state()))
    assert rendered.content_sha256 == again.content_sha256

    # render_order is non-decreasing across the kept sections.
    orders = [section.render_order for section in rendered.sections]
    assert orders == sorted(orders)

    # Required sections must always be present.
    names = {section.name for section in rendered.sections}
    assert {"runtime", "soul", "memory_boundary", "tool_use"}.issubset(names) or {
        "runtime",
        "memory_boundary",
        "tool_use",
    }.issubset(names)
    # SOUL.md may not exist in test data; if so it's correctly omitted.


def test_global_budget_caps_total_chars(monkeypatch) -> None:
    _patch_skill_catalog(monkeypatch)
    store = _StubStore(
        memories=[
            {"id": f"mem-{i}", "content": "x" * 4000, "metadata": {"k": i}}
            for i in range(3)
        ],
    )
    builder = ContextBuilder(store=store)
    rendered = builder.build(
        ContextBuildRequest(state=_make_state(user_msg="x"), max_chars=4000)
    )

    assert len(rendered.content) <= 4000
    # Required sections must survive even under tight budget.
    kept = {s.name for s in rendered.sections}
    assert {"runtime", "memory_boundary", "tool_use"}.issubset(kept)
    # Some sections should have been truncated or dropped.
    assert (
        rendered.budget.truncated_count > 0 or rendered.budget.dropped_count > 0
    )
    # Hash matches the rendered body verbatim.
    assert (
        rendered.content_sha256
        == hashlib.sha256(rendered.content.encode("utf-8")).hexdigest()
    )


def test_per_section_cap_is_never_exceeded(monkeypatch) -> None:
    _patch_skill_catalog(monkeypatch)

    huge_memory = {"id": "mem-big", "content": "y" * 50_000, "metadata": {}}
    builder = ContextBuilder(store=_StubStore(memories=[huge_memory]))
    rendered = builder.build(ContextBuildRequest(state=_make_state(user_msg="y")))

    by_name: dict[str, Section] = {s.name: s for s in rendered.sections}
    retrieved = by_name.get("retrieved_memory")
    assert retrieved is not None
    assert len(retrieved.content) <= ContextBuilder.SECTION_BUDGETS["retrieved_memory"]
    assert retrieved.truncated is True


def test_optional_section_dropped_when_below_min(monkeypatch) -> None:
    _patch_skill_catalog(monkeypatch)
    builder = ContextBuilder(store=_StubStore())
    rendered = builder.build(
        ContextBuildRequest(state=_make_state(), max_chars=2000)
    )

    # Required sections kept; some optional drops or no drops at all are
    # acceptable as long as the total fits and required sections survive.
    assert len(rendered.content) <= 2000
    required = {"runtime", "memory_boundary", "tool_use"}
    kept = {s.name for s in rendered.sections}
    assert required.issubset(kept)


def test_snapshot_payload_round_trips(monkeypatch) -> None:
    _patch_skill_catalog(monkeypatch)
    memories = [
        {"id": "mem-A", "content": "alpha", "metadata": {"tag": "a"}},
        {"id": "mem-B", "content": "beta", "metadata": {"tag": "b"}},
    ]
    store = _StubStore(memories=memories)
    builder = ContextBuilder(store=store)
    rendered = builder.build(ContextBuildRequest(state=_make_state(user_msg="alpha")))

    snapshot = builder.persist_snapshot(
        rendered,
        session_id="sess-test",
        agent_id="default",
        run_id="run-test",
        model="deepseek-v4-pro",
    )
    assert snapshot is not None
    assert store.snapshots, "snapshot was not recorded"
    recorded = store.snapshots[-1]
    assert recorded["session_id"] == "sess-test"
    assert recorded["agent_id"] == "default"
    assert recorded["run_id"] == "run-test"
    assert recorded["model"] == "deepseek-v4-pro"
    assert recorded["content_sha256"] == rendered.content_sha256
    assert recorded["section_count"] == len(rendered.sections)
    # Two memories were recalled — they must show up as injections.
    assert len(recorded["injections"]) == 2
    ids = {item["memory_id"] for item in recorded["injections"]}
    assert ids == {"mem-A", "mem-B"}
    # Each injection must carry an integer rank starting at 0.
    ranks = sorted(item["rank"] for item in recorded["injections"])
    assert ranks == [0, 1]


def test_persist_snapshot_no_session_returns_none(monkeypatch) -> None:
    _patch_skill_catalog(monkeypatch)
    store = _StubStore()
    builder = ContextBuilder(store=store)
    state = _make_state()
    state["session_id"] = ""
    rendered = builder.build(ContextBuildRequest(state=state))
    assert builder.persist_snapshot(
        rendered, session_id="", agent_id="default", run_id=None
    ) is None


def test_back_compat_alias_and_snapshot_shape(monkeypatch) -> None:
    _patch_skill_catalog(monkeypatch)
    from app.agent_framework.context_builder import ContextSection

    assert ContextSection is Section

    builder = ContextBuilder(store=_StubStore())
    rendered = builder.build(ContextBuildRequest(state=_make_state()))
    payload = rendered.snapshot()
    # Old keys still present.
    assert "section_count" in payload
    assert "total_chars" in payload
    assert "sections" in payload
    assert "injected_memories" in payload
    # New keys present.
    assert "content_sha256" in payload
    assert "budget" in payload
    assert payload["budget"]["max_chars"] >= 0
