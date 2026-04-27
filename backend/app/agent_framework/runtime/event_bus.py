"""EventBus — the single durable publication point for run events.

This module is the blueprint-canonical name for the existing
``RunEventService`` implementation. The semantics are identical:

* every non-token event is appended to ``run_events`` (durable replay log)
  and fanned out to live SSE subscribers in one atomic operation;
* token events stay transient (bounded ring buffer per run) and never
  hit the database;
* late subscribers replay history from ``after_sequence`` before joining
  the live fan-out, with sequence-based de-duplication.

Future stages (S2+) will attach memory-injection / prompt-snapshot events
through this same surface so trace, replay, and eval all observe the
identical stream the frontend sees.
"""

from __future__ import annotations

from .event_service import RunEventService

EventBus = RunEventService

__all__ = ["EventBus", "RunEventService"]
