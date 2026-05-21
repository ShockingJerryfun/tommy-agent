"""SkillForge — mine, propose, shadow-validate, promote, retire.

The forge is intentionally heuristic-first: skill mining is a frequency
analysis over recent ``tool_calls`` rows (per session, sliding window of
size two). Every successful run keeps an audit row in
``skill_forge_runs`` so an operator can backtrack any decision.

Promotions are gated on human review. The ``promote``
method requires a proposal that already reached ``status='applied'`` in
the ``skill_proposals`` queue; until then the catalog row stays
in ``shadow``. ``run_nightly`` therefore only ever produces *candidates*
— a human flips them live. ``retire`` is the one auto-action allowed:
under-performing skills get demoted without review.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ..memory_platform import Embedder, make_embedder
from ..storage import PostgresAgentStore, get_agent_store
from .catalog import SkillCatalog

ToolChain = tuple[str, ...]


@dataclass
class SkillForgeOutcome:
    """Result of a single Forge invocation across all four kinds."""

    mined: list[ToolChain] = field(default_factory=list)
    proposed_skill_ids: list[str] = field(default_factory=list)
    validated_skill_ids: list[str] = field(default_factory=list)
    promoted_skill_ids: list[str] = field(default_factory=list)
    retired_skill_ids: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mined": [list(chain) for chain in self.mined],
            "proposed_skill_ids": list(self.proposed_skill_ids),
            "validated_skill_ids": list(self.validated_skill_ids),
            "promoted_skill_ids": list(self.promoted_skill_ids),
            "retired_skill_ids": list(self.retired_skill_ids),
            "summary": self.summary,
        }


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", value.lower()).strip("-")
    return cleaned or "skill"


def _signature(chain: ToolChain, *, sample_args: list[dict[str, Any]] | None = None) -> str:
    """Compact textual signature used for embedding + dedup."""

    parts = [f"chain:{'->'.join(chain)}"]
    if sample_args:
        keys = sorted({k for args in sample_args[:5] for k in (args or {}).keys()})
        if keys:
            parts.append("inputs:" + ",".join(keys[:8]))
    return " | ".join(parts)


def _skill_markdown(name: str, chain: ToolChain, rationale: str) -> str:
    chain_str = " → ".join(chain) if chain else "(empty)"
    return (
        f"---\n"
        f'name: "{name}"\n'
        f'description: "Auto-mined skill chaining {chain_str}."\n'
        f"---\n\n"
        f"# {name}\n\n"
        f"**Tool chain:** `{chain_str}`\n\n"
        f"## Rationale\n\n{rationale}\n\n"
        f"## Usage\n\n"
        f"This skill captures a frequently-occurring tool sequence. The agent "
        f"should consider invoking the chain end-to-end when the user's "
        f"request matches the skill signature.\n"
    )


def _same_tool_chain(value: Any, chain: ToolChain) -> bool:
    if not isinstance(value, list):
        return False
    return tuple(str(item) for item in value) == chain


class SkillForge:
    """Mine + validate + (operator-)promote skills from tool history."""

    def __init__(
        self,
        store: PostgresAgentStore | None = None,
        *,
        embedder: Embedder | None = None,
        catalog: SkillCatalog | None = None,
    ) -> None:
        self._store = store or get_agent_store()
        self._embedder = embedder or make_embedder()
        self._catalog = catalog  # SkillCatalog (filesystem) is lazily resolved per agent

    # ------------------------------------------------------------------
    # 1. mine
    # ------------------------------------------------------------------
    def mine(
        self,
        *,
        agent_id: str,
        min_frequency: int = 2,
        chain_size: int = 2,
        max_sessions: int = 50,
    ) -> list[ToolChain]:
        """Walk recent sessions' tool_calls and surface frequent chains."""

        sessions = self._store.list_sessions(agent_id=agent_id)[:max_sessions]
        chain_counter: Counter[ToolChain] = Counter()
        for session in sessions:
            calls = self._store.list_tool_calls(session["id"])
            names = [str(c.get("name") or "") for c in calls if c.get("status") != "error"]
            names = [n for n in names if n]
            if len(names) < chain_size:
                continue
            for i in range(0, len(names) - chain_size + 1):
                window = tuple(names[i : i + chain_size])
                if len(set(window)) == 1:
                    # Skip same-tool repetitions — those are loops, not skills.
                    continue
                chain_counter[window] += 1
        mined = [chain for chain, count in chain_counter.items() if count >= min_frequency]
        self._store.skill_forge_runs.append(
            agent_id=agent_id,
            kind="mine",
            inputs_count=len(sessions),
            proposals_count=len(mined),
            summary=(
                f"Scanned {len(sessions)} sessions, found {len(mined)} candidate "
                f"chains at min_frequency={min_frequency}."
            ),
            metrics={
                "candidates": [{"chain": list(c), "count": chain_counter[c]} for c in mined],
            },
        )
        return mined

    def list_skills(self, *, agent_id: str, status: str, limit: int = 100) -> list[dict[str, Any]]:
        return self._store.skill_catalog.list_skills(agent_id=agent_id, status=status, limit=limit)

    # ------------------------------------------------------------------
    # 2. propose
    # ------------------------------------------------------------------
    def propose(
        self,
        *,
        agent_id: str,
        chain: ToolChain,
        rationale: str = "",
        sample_args: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Register a shadow skill row + queue a markdown proposal."""

        if not chain:
            raise ValueError("propose() requires a non-empty tool chain")
        chain = tuple(chain)
        skill_name = "skill_" + "_".join(_slug(t) for t in chain)
        relative_path = f"{skill_name}/SKILL.md"
        signature = _signature(chain, sample_args=sample_args)

        existing = self._existing_pending_forge_proposal(
            agent_id=agent_id,
            chain=chain,
            relative_path=relative_path,
        )
        if existing is not None:
            return existing

        markdown = _skill_markdown(
            name=skill_name,
            chain=chain,
            rationale=rationale or f"Auto-mined chain {' -> '.join(chain)}.",
        )

        proposal = self._store.create_skill_proposal(
            agent_id=agent_id,
            name=skill_name,
            relative_path=relative_path,
            action="create",
            rationale=rationale or f"Forge-mined chain {' -> '.join(chain)}",
            content=markdown,
            risks=["auto-mined", "shadow-only until validated and human-approved"],
            metadata={
                "source": "skill_forge",
                "tool_chain": list(chain),
                "auto_promote": False,
            },
        )

        catalog_row = self._store.skill_catalog.register_skill(
            agent_id=agent_id,
            name=skill_name,
            relative_path=relative_path,
            description=f"Auto-mined chain {' → '.join(chain)}",
            signature=signature,
            tool_chain=list(chain),
            status="shadow",
            metadata={"forge_chain": list(chain)},
            metrics={"validated": False},
            proposal_id=proposal["id"],
        )

        embedding = self._embedder.embed(signature)
        if embedding:
            self._store.skill_catalog.update_signature_embedding(
                catalog_row["id"],
                embedding=embedding,
                model=getattr(self._embedder, "model_name", "embedder"),
            )

        return {
            "proposal": proposal,
            "skill": catalog_row,
            "signature": signature,
        }

    def _existing_pending_forge_proposal(
        self,
        *,
        agent_id: str,
        chain: ToolChain,
        relative_path: str,
    ) -> dict[str, Any] | None:
        proposals = self._store.list_skill_proposals(agent_id=agent_id, status="proposed")
        for proposal in proposals:
            metadata = proposal.get("metadata") or {}
            if metadata.get("source") != "skill_forge":
                continue
            if proposal.get("relative_path") != relative_path:
                continue
            if not _same_tool_chain(metadata.get("tool_chain"), chain):
                continue
            for skill in self._store.skill_catalog.list_skills(agent_id=agent_id, status="shadow"):
                if skill.get("proposal_id") == proposal["id"]:
                    return {
                        "proposal": proposal,
                        "skill": skill,
                        "signature": skill.get("signature") or _signature(chain),
                    }
        return None

    # ------------------------------------------------------------------
    # 3. shadow_validate
    # ------------------------------------------------------------------
    def shadow_validate(
        self,
        *,
        skill_id: str,
        sample_outcomes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Compute success/latency metrics for the candidate skill.

        ``sample_outcomes`` is the list of historical executions of the
        chain (each entry: ``{"success": bool, "latency_ms": float}``).
        Callers that don't pass outcomes get a zero-sample placeholder
        so the shadow remains explicitly un-validated.
        """

        skill = self._store.skill_catalog.get(skill_id)
        if skill is None:
            raise FileNotFoundError(f"Skill not found: {skill_id}")

        outcomes = list(sample_outcomes or [])
        successes = sum(1 for o in outcomes if o.get("success"))
        failures = len(outcomes) - successes
        latencies = [float(o.get("latency_ms", 0.0)) for o in outcomes]
        avg_latency = statistics.fmean(latencies) if latencies else 0.0
        if len(latencies) >= 20:
            p95_latency = statistics.quantiles(latencies, n=20)[-1]
        else:
            p95_latency = max(latencies, default=0.0)
        success_rate = (successes / len(outcomes)) if outcomes else 0.0

        metrics = {
            "validated": bool(outcomes),
            "sample_size": len(outcomes),
            "success_count": successes,
            "failure_count": failures,
            "success_rate": success_rate,
            "avg_latency_ms": avg_latency,
            "p95_latency_ms": p95_latency,
        }

        self._store.skill_catalog.update_metrics(skill_id, metrics=metrics)
        self._store.skill_forge_runs.append(
            agent_id=skill["agent_id"],
            kind="validate",
            inputs_count=len(outcomes),
            proposals_count=0,
            summary=(
                f"Shadow-validated skill {skill_id} on {len(outcomes)} samples, "
                f"success_rate={success_rate:.2f}."
            ),
            metrics={"skill_id": skill_id, **metrics},
        )
        return metrics

    # ------------------------------------------------------------------
    # 4. promote (requires human-applied proposal)
    # ------------------------------------------------------------------
    def promote(
        self,
        *,
        skill_id: str,
        reviewer: str = "human",
    ) -> dict[str, Any]:
        skill = self._store.skill_catalog.get(skill_id)
        if skill is None:
            raise FileNotFoundError(f"Skill not found: {skill_id}")
        proposal_id = skill.get("proposal_id")
        proposal = self._store.get_skill_proposal(proposal_id) if proposal_id else None
        if not proposal or proposal["status"] != "applied":
            raise PermissionError(
                "Skill cannot be promoted until its SkillProposal reaches "
                "status='applied' (human review queue)."
            )

        promoted = self._store.skill_catalog.set_status(skill_id, "active")
        version_id = proposal.get("version_id")
        if promoted is not None and version_id and not promoted.get("version_id"):
            promoted = self._store.skill_catalog.set_version(skill_id, str(version_id))

        self._store.skill_forge_runs.append(
            agent_id=skill["agent_id"],
            kind="promote",
            inputs_count=1,
            proposals_count=1,
            summary=f"Promoted {skill_id} to active by {reviewer}.",
            metrics={"skill_id": skill_id, "reviewer": reviewer},
        )
        return promoted or {}

    # ------------------------------------------------------------------
    # 5. retire
    # ------------------------------------------------------------------
    def retire(
        self,
        *,
        skill_id: str,
        reason: str = "",
    ) -> dict[str, Any]:
        skill = self._store.skill_catalog.get(skill_id)
        if skill is None:
            raise FileNotFoundError(f"Skill not found: {skill_id}")
        retired = self._store.skill_catalog.set_status(skill_id, "retired")
        self._store.skill_forge_runs.append(
            agent_id=skill["agent_id"],
            kind="retire",
            inputs_count=1,
            proposals_count=0,
            summary=f"Retired {skill_id}: {reason}" if reason else f"Retired {skill_id}.",
            metrics={"skill_id": skill_id, "reason": reason},
        )
        return retired or {}


_DEFAULT_FORGE: SkillForge | None = None


def get_default_skill_forge(
    store: PostgresAgentStore | None = None,
) -> SkillForge:
    global _DEFAULT_FORGE
    if _DEFAULT_FORGE is None:
        _DEFAULT_FORGE = SkillForge(store=store)
    return _DEFAULT_FORGE
