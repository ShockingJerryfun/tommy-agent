"""Observability & evaluation primitives.

Public surface:

- :func:`get_tracer` — OTel tracer (no-op if no SDK is configured).
- :func:`span` — context manager for a single OTel span (also a no-op
  fallback). Always safe to call regardless of provider state.
- :class:`RunMetricsRecorder` — typed recorder that flushes a single
  per-run metrics row to Postgres on ``finalize``.
- :func:`replay_session` — replay harness that re-executes a session's
  user inputs through an injectable runner and compares deterministic
  signals (final response, prompt snapshots, citation counts).
- :mod:`eval_suites` — small, deterministic eval suites (tool safety,
  recall, compaction, loop, hallucination).
- :class:`MaintenanceScheduler` — asyncio in-proc scheduler used by
  the FastAPI lifespan to periodically run maintenance jobs (memory
  decay, stale approval cleanup, skill forge nightly).
"""

from __future__ import annotations

from .maintenance import (
    MaintenanceJob,
    MaintenanceScheduler,
    default_maintenance_jobs,
)
from .metrics import RunMetricsRecorder
from .replay import (
    ReplayReport,
    ReplayRunner,
    default_replay_runner,
    replay_session,
)
from .tracer import get_tracer, span

__all__ = [
    "MaintenanceJob",
    "MaintenanceScheduler",
    "ReplayReport",
    "ReplayRunner",
    "RunMetricsRecorder",
    "default_maintenance_jobs",
    "default_replay_runner",
    "get_tracer",
    "replay_session",
    "span",
]
