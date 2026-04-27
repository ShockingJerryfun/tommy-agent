"""Tests for the S5 Skills & Forge pipeline."""

from __future__ import annotations

import uuid

from app.agent_framework.memory_platform import EchoEmbedder
from app.agent_framework.skills_forge import (
    SkillActivator,
    SkillForge,
    run_nightly,
)
from app.agent_framework.store import PostgresAgentStore


def _store() -> PostgresAgentStore:
    store = PostgresAgentStore()
    store.reset_for_tests()
    return store


def _new_session(store: PostgresAgentStore, *, agent_id: str = "default") -> str:
    session_id = f"sess-{uuid.uuid4().hex[:10]}"
    store.create_session(session_id=session_id, agent_id=agent_id, title="t")
    return session_id


def _seed_tool_calls(
    store: PostgresAgentStore,
    session_id: str,
    *,
    chain: list[str],
    repeats: int = 1,
) -> None:
    for round_idx in range(repeats):
        for i, name in enumerate(chain):
            store.upsert_tool_call(
                session_id,
                run_id=f"run-{session_id}-{round_idx}",
                tool_call_id=f"tc-{session_id}-{round_idx}-{i}",
                name=name,
                status="ok",
                args={"i": i},
                result="ok",
            )


# ---------------------------------------------------------------------------
# Catalog repo
# ---------------------------------------------------------------------------


def test_register_skill_round_trip_and_idempotent_upsert():
    store = _store()
    row = store.skill_catalog.register_skill(
        agent_id="default",
        name="skill_search_then_summarize",
        relative_path="skill_search_then_summarize/SKILL.md",
        signature="chain:web_search->context_pact_update",
        description="search → summarize",
        tool_chain=["web_search", "context_pact_update"],
    )
    assert row["status"] == "shadow"
    assert row["tool_chain"] == ["web_search", "context_pact_update"]

    fetched = store.skill_catalog.get_by_path(
        agent_id="default",
        relative_path="skill_search_then_summarize/SKILL.md",
    )
    assert fetched is not None
    assert fetched["id"] == row["id"]

    # Re-registering the same path must upsert, not duplicate.
    again = store.skill_catalog.register_skill(
        agent_id="default",
        name="skill_search_then_summarize",
        relative_path="skill_search_then_summarize/SKILL.md",
        signature="chain:web_search->context_pact_update v2",
        tool_chain=["web_search", "context_pact_update"],
    )
    assert again["id"] == row["id"]
    assert "v2" in again["signature"]


def test_record_invocation_updates_counters_and_avg_latency():
    store = _store()
    row = store.skill_catalog.register_skill(
        agent_id="default",
        name="skill_a",
        relative_path="skill_a/SKILL.md",
        signature="sig",
    )
    store.skill_catalog.set_status(row["id"], "active")

    store.skill_catalog.record_invocation(row["id"], success=True, latency_ms=100.0)
    after_one = store.skill_catalog.get(row["id"])
    assert after_one["invocation_count"] == 1
    assert after_one["success_count"] == 1
    assert after_one["avg_latency_ms"] == 100.0
    assert after_one["last_used_at"] is not None

    store.skill_catalog.record_invocation(row["id"], success=False, latency_ms=200.0)
    after_two = store.skill_catalog.get(row["id"])
    assert after_two["invocation_count"] == 2
    assert after_two["failure_count"] == 1
    assert after_two["avg_latency_ms"] == 150.0


def test_search_signature_returns_nearest_active_skill():
    store = _store()
    embedder = EchoEmbedder()

    a = store.skill_catalog.register_skill(
        agent_id="default",
        name="skill_a",
        relative_path="skill_a/SKILL.md",
        signature="research a topic and summarize results",
    )
    b = store.skill_catalog.register_skill(
        agent_id="default",
        name="skill_b",
        relative_path="skill_b/SKILL.md",
        signature="rotate database backups nightly",
    )
    for skill in (a, b):
        store.skill_catalog.set_status(skill["id"], "active")
        store.skill_catalog.update_signature_embedding(
            skill["id"],
            embedding=embedder.embed(skill["signature"]),
            model="echo",
        )

    hits = store.skill_catalog.search_signature(
        agent_id="default",
        embedding=embedder.embed("research a topic and summarize results"),
        limit=1,
    )
    assert len(hits) == 1
    assert hits[0]["id"] == a["id"]
    assert 0.0 <= hits[0]["similarity"] <= 1.0


# ---------------------------------------------------------------------------
# Activator
# ---------------------------------------------------------------------------


def test_activator_recall_filters_by_status_active():
    store = _store()
    embedder = EchoEmbedder()
    activator = SkillActivator(store=store, embedder=embedder)

    shadow = store.skill_catalog.register_skill(
        agent_id="default",
        name="skill_shadow",
        relative_path="skill_shadow/SKILL.md",
        signature="shadow query about widgets",
    )
    store.skill_catalog.update_signature_embedding(
        shadow["id"], embedding=embedder.embed("shadow query about widgets"), model="echo"
    )

    active = store.skill_catalog.register_skill(
        agent_id="default",
        name="skill_active",
        relative_path="skill_active/SKILL.md",
        signature="shadow query about widgets",
    )
    store.skill_catalog.set_status(active["id"], "active")
    store.skill_catalog.update_signature_embedding(
        active["id"], embedding=embedder.embed("shadow query about widgets"), model="echo"
    )

    hits = activator.recall(agent_id="default", query="shadow query about widgets", k=5)
    assert [h.skill_id for h in hits] == [active["id"]]
    assert hits[0].name == "skill_active"

    # Including ``shadow`` returns both ranked.
    hits_all = activator.recall(
        agent_id="default",
        query="shadow query about widgets",
        k=5,
        statuses=("active", "shadow"),
    )
    assert {h.skill_id for h in hits_all} == {active["id"], shadow["id"]}


def test_activator_returns_empty_for_blank_query():
    activator = SkillActivator(store=_store(), embedder=EchoEmbedder())
    assert activator.recall(agent_id="default", query="") == []
    assert activator.recall(agent_id="default", query="   ") == []


# ---------------------------------------------------------------------------
# Forge — mine / propose / shadow_validate / promote / retire
# ---------------------------------------------------------------------------


def test_forge_mine_finds_repeated_chains_and_audits_the_run():
    store = _store()
    forge = SkillForge(store=store, embedder=EchoEmbedder())

    s1 = _new_session(store)
    s2 = _new_session(store)
    s3 = _new_session(store)
    _seed_tool_calls(store, s1, chain=["web_search", "context_pact_update"])
    _seed_tool_calls(store, s2, chain=["web_search", "context_pact_update"])
    _seed_tool_calls(store, s3, chain=["read_workspace_file", "skill_propose"])

    chains = forge.mine(agent_id="default", min_frequency=2, chain_size=2)
    assert ("web_search", "context_pact_update") in chains
    assert ("read_workspace_file", "skill_propose") not in chains  # only once

    runs = store.skill_forge_runs.list_runs(agent_id="default", kind="mine")
    assert len(runs) == 1
    assert runs[0]["proposals_count"] == len(chains)


def test_forge_propose_creates_shadow_skill_and_human_review_proposal():
    store = _store()
    forge = SkillForge(store=store, embedder=EchoEmbedder())

    out = forge.propose(
        agent_id="default",
        chain=("web_search", "context_pact_update"),
        rationale="frequent search-then-summarize pattern",
    )
    assert out["skill"]["status"] == "shadow"
    assert out["skill"]["proposal_id"] == out["proposal"]["id"]
    assert out["proposal"]["status"] == "proposed"
    assert "skill_web_search_context_pact_update" in out["skill"]["name"]

    refreshed = store.skill_catalog.get(out["skill"]["id"])
    assert refreshed["embedding_model"] != ""  # signature embedding was set


def test_forge_shadow_validate_persists_metrics():
    store = _store()
    forge = SkillForge(store=store, embedder=EchoEmbedder())
    out = forge.propose(agent_id="default", chain=("web_search", "context_pact_update"))

    metrics = forge.shadow_validate(
        skill_id=out["skill"]["id"],
        sample_outcomes=[
            {"success": True, "latency_ms": 80.0},
            {"success": True, "latency_ms": 90.0},
            {"success": False, "latency_ms": 250.0},
        ],
    )
    assert metrics["validated"] is True
    assert metrics["sample_size"] == 3
    assert metrics["success_count"] == 2
    assert 0.6 < metrics["success_rate"] < 0.7
    assert metrics["avg_latency_ms"] == 140.0

    refreshed = store.skill_catalog.get(out["skill"]["id"])
    assert refreshed["metrics"]["validated"] is True
    assert refreshed["metrics"]["success_count"] == 2


def test_forge_promote_requires_human_applied_proposal():
    store = _store()
    forge = SkillForge(store=store, embedder=EchoEmbedder())
    out = forge.propose(agent_id="default", chain=("web_search", "context_pact_update"))

    # Without applying the proposal first, promote() must refuse.
    try:
        forge.promote(skill_id=out["skill"]["id"])
    except PermissionError as exc:
        assert "human review" in str(exc) or "applied" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("promote() should refuse before human review")

    # Simulate human review by flipping the proposal to ``applied`` (the
    # filesystem write is exercised by SkillCatalog tests; here we just
    # need the status flip to unblock promote()).
    store.apply_skill_proposal(
        out["proposal"]["id"],
        version_id=f"skill-ver-{uuid.uuid4().hex}",
        previous_content="",
    )
    promoted = forge.promote(skill_id=out["skill"]["id"], reviewer="alice")
    assert promoted["status"] == "active"
    assert promoted["version_id"] is not None

    runs = store.skill_forge_runs.list_runs(agent_id="default", kind="promote")
    assert runs and runs[0]["metrics"]["reviewer"] == "alice"


def test_forge_retire_demotes_active_skill():
    store = _store()
    forge = SkillForge(store=store, embedder=EchoEmbedder())
    row = store.skill_catalog.register_skill(
        agent_id="default",
        name="skill_to_retire",
        relative_path="skill_to_retire/SKILL.md",
        signature="sig",
    )
    store.skill_catalog.set_status(row["id"], "active")

    retired = forge.retire(skill_id=row["id"], reason="poor success rate")
    assert retired["status"] == "retired"

    runs = store.skill_forge_runs.list_runs(agent_id="default", kind="retire")
    assert runs and runs[0]["metrics"]["reason"] == "poor success rate"


# ---------------------------------------------------------------------------
# Nightly pipeline
# ---------------------------------------------------------------------------


def test_run_nightly_mines_proposes_validates_and_auto_retires():
    store = _store()
    forge = SkillForge(store=store, embedder=EchoEmbedder())

    # Two sessions exhibiting the same chain → mine threshold (2) hit.
    s1 = _new_session(store)
    s2 = _new_session(store)
    _seed_tool_calls(store, s1, chain=["web_search", "context_pact_update"])
    _seed_tool_calls(store, s2, chain=["web_search", "context_pact_update"])

    # Pre-existing active skill with bad metrics → must be auto-retired.
    bad = store.skill_catalog.register_skill(
        agent_id="default",
        name="skill_bad",
        relative_path="skill_bad/SKILL.md",
        signature="bad sig",
    )
    store.skill_catalog.set_status(bad["id"], "active")
    for _ in range(8):
        store.skill_catalog.record_invocation(bad["id"], success=False, latency_ms=10.0)
    # And one with a healthy rate that must stay active.
    good = store.skill_catalog.register_skill(
        agent_id="default",
        name="skill_good",
        relative_path="skill_good/SKILL.md",
        signature="good sig",
    )
    store.skill_catalog.set_status(good["id"], "active")
    for _ in range(8):
        store.skill_catalog.record_invocation(good["id"], success=True, latency_ms=10.0)

    outcome = run_nightly(agent_id="default", forge=forge, min_frequency=2)
    assert ("web_search", "context_pact_update") in outcome.mined
    assert outcome.proposed_skill_ids
    assert outcome.validated_skill_ids
    assert bad["id"] in outcome.retired_skill_ids
    assert good["id"] not in outcome.retired_skill_ids

    # The retired skill is now status='retired'.
    assert store.skill_catalog.get(bad["id"])["status"] == "retired"
    assert store.skill_catalog.get(good["id"])["status"] == "active"


def test_run_nightly_does_not_auto_promote():
    store = _store()
    forge = SkillForge(store=store, embedder=EchoEmbedder())

    s1 = _new_session(store)
    s2 = _new_session(store)
    _seed_tool_calls(store, s1, chain=["web_search", "context_pact_update"])
    _seed_tool_calls(store, s2, chain=["web_search", "context_pact_update"])

    outcome = run_nightly(agent_id="default", forge=forge, min_frequency=2)
    assert outcome.proposed_skill_ids
    assert outcome.promoted_skill_ids == []  # human review is mandatory

    for skill_id in outcome.proposed_skill_ids:
        skill = store.skill_catalog.get(skill_id)
        assert skill["status"] == "shadow"
