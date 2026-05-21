"""Nightly Forge orchestration."""

from __future__ import annotations

from .forge import SkillForge, SkillForgeOutcome, get_default_skill_forge


def run_nightly(
    *,
    agent_id: str,
    forge: SkillForge | None = None,
    min_frequency: int = 2,
    chain_size: int = 2,
    auto_retire_below_success_rate: float = 0.4,
    auto_retire_min_samples: int = 5,
) -> SkillForgeOutcome:
    """End-to-end forge pass — mine, propose, shadow-validate, retire.

    Promotion is *not* attempted automatically: the catalog row stays in
    ``shadow`` until a human reviewer flips the matching SkillProposal
    to ``applied`` and explicitly calls :meth:`SkillForge.promote`.
    """

    forge = forge or get_default_skill_forge()
    outcome = SkillForgeOutcome()

    chains = forge.mine(
        agent_id=agent_id,
        min_frequency=min_frequency,
        chain_size=chain_size,
    )
    outcome.mined.extend(chains)

    for chain in chains:
        proposal = forge.propose(agent_id=agent_id, chain=chain)
        skill_id = proposal["skill"]["id"]
        outcome.proposed_skill_ids.append(skill_id)

    # Shadow-validate every shadow skill we know about; in production the
    # outcomes list would come from replaying historical traces. Here we
    # consult the per-skill metadata for any seeded sample outcomes,
    # falling back to an empty list so the row is left explicitly
    # un-validated.
    shadow_skills = forge.list_skills(agent_id=agent_id, status="shadow")
    for skill in shadow_skills:
        sample_outcomes = (skill.get("metadata") or {}).get("sample_outcomes")
        forge.shadow_validate(
            skill_id=skill["id"],
            sample_outcomes=sample_outcomes if isinstance(sample_outcomes, list) else None,
        )
        outcome.validated_skill_ids.append(skill["id"])

    # Auto-retire any active skill whose live metrics have decayed below
    # the threshold. We touch only invocation_count >= auto_retire_min_samples
    # so we don't punish freshly promoted skills.
    active_skills = forge.list_skills(agent_id=agent_id, status="active")
    for skill in active_skills:
        invocations = int(skill.get("invocation_count") or 0)
        successes = int(skill.get("success_count") or 0)
        if invocations < auto_retire_min_samples:
            continue
        success_rate = successes / max(invocations, 1)
        if success_rate < auto_retire_below_success_rate:
            forge.retire(
                skill_id=skill["id"],
                reason=(
                    f"auto-retired: success_rate={success_rate:.2f} < "
                    f"{auto_retire_below_success_rate:.2f} over {invocations} runs"
                ),
            )
            outcome.retired_skill_ids.append(skill["id"])

    outcome.summary = _summary(outcome)
    return outcome


def _summary(outcome: SkillForgeOutcome) -> str:
    parts: list[str] = []
    if outcome.mined:
        parts.append(f"mined={len(outcome.mined)}")
    if outcome.proposed_skill_ids:
        parts.append(f"proposed={len(outcome.proposed_skill_ids)}")
    if outcome.validated_skill_ids:
        parts.append(f"validated={len(outcome.validated_skill_ids)}")
    if outcome.retired_skill_ids:
        parts.append(f"retired={len(outcome.retired_skill_ids)}")
    return ", ".join(parts) or "noop"

__all__ = ["run_nightly"]
