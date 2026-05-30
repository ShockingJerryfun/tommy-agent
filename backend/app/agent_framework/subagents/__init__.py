"""Subagents — bounded child agents with scoped tools and parent linkage.

Public surface:

- :class:`SubagentRole` — declarative role spec (id, system prompt,
  tool whitelist, permission overrides).
- :func:`role_registry` / :func:`registry_for_role` — pluggable
  registry resolution; the default roles are ``researcher``,
  ``analyst``, and ``writer``.
- :class:`SubagentDelegator` — runs a single subagent attempt and
  persists the parent ↔ child link in ``subagent_runs``.
- :class:`BestOfNMerger` — runs N attempts (sequentially), scores each
  deterministically, picks the winner, marks losers as completed but
  with lower scores, and returns a merged response.
- :func:`subagent_summary_section` — used by the ContextBuilder to inject
  a compact summary of recent subagent results into the parent prompt.
"""

from __future__ import annotations

from .delegate import (
    SubagentDelegator,
    SubagentResult,
    SubagentRunner,
    default_subagent_runner,
)
from .hermes import (
    HermesDelegateConfig,
    HermesDelegateUnavailable,
    hermes_result_events,
    run_hermes_delegate,
)
from .merger import BestOfNMerger, MergedSubagentResult, score_response
from .orchestrator import create_subagent_registry, run_delegate_task
from .roles import (
    SubagentRole,
    list_role_ids,
    registry_for_role,
    resolve_role,
    role_registry,
)
from .summary import (
    SubagentSummary,
    list_recent_summaries,
    subagent_summary_markdown,
    subagent_summary_section,
)

__all__ = [
    "BestOfNMerger",
    "create_subagent_registry",
    "HermesDelegateConfig",
    "HermesDelegateUnavailable",
    "hermes_result_events",
    "MergedSubagentResult",
    "SubagentDelegator",
    "SubagentResult",
    "SubagentRole",
    "SubagentRunner",
    "SubagentSummary",
    "default_subagent_runner",
    "list_recent_summaries",
    "list_role_ids",
    "registry_for_role",
    "resolve_role",
    "role_registry",
    "run_delegate_task",
    "run_hermes_delegate",
    "score_response",
    "subagent_summary_markdown",
    "subagent_summary_section",
]
