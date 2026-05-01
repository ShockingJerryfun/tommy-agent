"""Skills & Forge — S5.

Public surface:

- :class:`SkillActivator` — query the canonical ``skills`` table by
  embedding nearest-neighbor on ``signature_embedding`` (HNSW). Cheap to
  instantiate; share an embedder across calls.
- :class:`SkillForge` — the nightly pipeline. ``mine`` walks the recent
  ``tool_calls`` history, ``propose`` materialises candidate skills as
  ``status='shadow'`` rows + a markdown ``SkillProposal`` queued for
  human review, ``shadow_validate`` evaluates the candidate against
  held-out traces and persists metrics, ``promote`` flips the status to
  ``active`` (requires a human-applied proposal per blueprint §13), and
  ``retire`` demotes underperforming skills.
- :func:`run_nightly` — convenience orchestrator (mine → propose →
  shadow_validate → retire).
"""

from __future__ import annotations

from .activator import SkillActivator, SkillCandidate, get_default_skill_activator
from .catalog import SkillCatalog, SkillProposal, SkillSummary
from .forge import SkillForge, SkillForgeOutcome, ToolChain, get_default_skill_forge
from .pipeline import run_nightly

__all__ = [
    "SkillCatalog",
    "SkillActivator",
    "SkillCandidate",
    "SkillForge",
    "SkillForgeOutcome",
    "SkillProposal",
    "SkillSummary",
    "ToolChain",
    "get_default_skill_activator",
    "get_default_skill_forge",
    "run_nightly",
]
