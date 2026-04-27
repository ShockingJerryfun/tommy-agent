"""Hard-cap Budget for cognitive graph runs.

Per blueprint §13 the cognitive nodes must never loop unbounded. The
Budget tracks four caps:

- ``max_turns`` — number of agent (LLM) invocations
- ``max_tool_calls`` — number of tool executions across the run
- ``max_wall_seconds`` — wall-clock seconds since ``pre_run``
- ``max_total_chars`` — cumulative assistant content emitted

When any cap is exhausted, ``Budget.exhausted`` flips to ``True`` with a
human-readable ``exhausted_reason``. The critic node treats this as a
hard stop and routes the run to the reflector → END regardless of
whether the model emitted more tool calls.

Defaults are conservative; they can be overridden per-run via
``state["metadata"]["budget"]`` (a dict with any subset of the cap
keys), or via env vars:

- ``TOMMY_BUDGET_MAX_TURNS``
- ``TOMMY_BUDGET_MAX_TOOL_CALLS``
- ``TOMMY_BUDGET_MAX_WALL_SECONDS``
- ``TOMMY_BUDGET_MAX_TOTAL_CHARS``
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field, replace
from typing import Any

DEFAULT_MAX_TURNS = 12
DEFAULT_MAX_TOOL_CALLS = 24
DEFAULT_MAX_WALL_SECONDS = 180.0
DEFAULT_MAX_TOTAL_CHARS = 80_000


@dataclass(frozen=True)
class Budget:
    max_turns: int = DEFAULT_MAX_TURNS
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS
    max_wall_seconds: float = DEFAULT_MAX_WALL_SECONDS
    max_total_chars: int = DEFAULT_MAX_TOTAL_CHARS
    turn_count: int = 0
    tool_call_count: int = 0
    total_chars: int = 0
    started_at: float = 0.0
    exhausted: bool = False
    exhausted_reason: str = ""
    notes: list[str] = field(default_factory=list)

    # ------------------------------------------------------------ helpers

    def elapsed(self) -> float:
        if self.started_at <= 0:
            return 0.0
        return max(0.0, time.time() - self.started_at)

    def evaluate(self) -> tuple[bool, str]:
        """Return ``(exhausted, reason)`` after applying every cap.

        The first violated cap wins; the order is the same as the
        evaluation order in :func:`Budget.tick` so callers never see a
        stale reason.
        """

        if self.turn_count > self.max_turns:
            return True, f"turn_cap:{self.max_turns}"
        if self.tool_call_count > self.max_tool_calls:
            return True, f"tool_call_cap:{self.max_tool_calls}"
        if self.total_chars > self.max_total_chars:
            return True, f"total_chars_cap:{self.max_total_chars}"
        if self.started_at > 0 and self.elapsed() > self.max_wall_seconds:
            return True, f"wall_seconds_cap:{int(self.max_wall_seconds)}"
        return False, ""

    def tick(
        self,
        *,
        new_turns: int = 0,
        new_tool_calls: int = 0,
        new_chars: int = 0,
        note: str | None = None,
    ) -> Budget:
        """Return a copy with counters incremented and exhaustion re-evaluated."""

        notes = list(self.notes)
        if note:
            notes.append(note)
        candidate = replace(
            self,
            turn_count=self.turn_count + max(0, int(new_turns)),
            tool_call_count=self.tool_call_count + max(0, int(new_tool_calls)),
            total_chars=self.total_chars + max(0, int(new_chars)),
            notes=notes,
        )
        exhausted, reason = candidate.evaluate()
        return replace(
            candidate, exhausted=exhausted, exhausted_reason=reason
        )

    def started(self) -> Budget:
        """Stamp ``started_at`` if not already started."""

        if self.started_at > 0:
            return self
        return replace(self, started_at=time.time())

    # ------------------------------------------------------------- I/O

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_turns": self.max_turns,
            "max_tool_calls": self.max_tool_calls,
            "max_wall_seconds": self.max_wall_seconds,
            "max_total_chars": self.max_total_chars,
            "turn_count": self.turn_count,
            "tool_call_count": self.tool_call_count,
            "total_chars": self.total_chars,
            "started_at": self.started_at,
            "elapsed_seconds": self.elapsed(),
            "exhausted": self.exhausted,
            "exhausted_reason": self.exhausted_reason,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Budget:
        data = data or {}
        return cls(
            max_turns=int(data.get("max_turns", DEFAULT_MAX_TURNS)),
            max_tool_calls=int(data.get("max_tool_calls", DEFAULT_MAX_TOOL_CALLS)),
            max_wall_seconds=float(
                data.get("max_wall_seconds", DEFAULT_MAX_WALL_SECONDS)
            ),
            max_total_chars=int(
                data.get("max_total_chars", DEFAULT_MAX_TOTAL_CHARS)
            ),
            turn_count=int(data.get("turn_count", 0)),
            tool_call_count=int(data.get("tool_call_count", 0)),
            total_chars=int(data.get("total_chars", 0)),
            started_at=float(data.get("started_at", 0.0)),
            exhausted=bool(data.get("exhausted", False)),
            exhausted_reason=str(data.get("exhausted_reason", "")),
            notes=list(data.get("notes", []) or []),
        )

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any] | None) -> Budget:
        """Build a fresh Budget honoring metadata + env-var overrides.

        Lookup precedence: ``metadata['budget'][key]`` > env var > default.
        """

        meta = (metadata or {}).get("budget") if isinstance(metadata, dict) else None
        meta = meta if isinstance(meta, dict) else {}

        def _int(key: str, env: str, default: int) -> int:
            if key in meta:
                try:
                    return int(meta[key])
                except (TypeError, ValueError):
                    pass
            env_value = os.getenv(env)
            if env_value:
                try:
                    return int(env_value)
                except ValueError:
                    pass
            return default

        def _float(key: str, env: str, default: float) -> float:
            if key in meta:
                try:
                    return float(meta[key])
                except (TypeError, ValueError):
                    pass
            env_value = os.getenv(env)
            if env_value:
                try:
                    return float(env_value)
                except ValueError:
                    pass
            return default

        return cls(
            max_turns=_int(
                "max_turns", "TOMMY_BUDGET_MAX_TURNS", DEFAULT_MAX_TURNS
            ),
            max_tool_calls=_int(
                "max_tool_calls",
                "TOMMY_BUDGET_MAX_TOOL_CALLS",
                DEFAULT_MAX_TOOL_CALLS,
            ),
            max_wall_seconds=_float(
                "max_wall_seconds",
                "TOMMY_BUDGET_MAX_WALL_SECONDS",
                DEFAULT_MAX_WALL_SECONDS,
            ),
            max_total_chars=_int(
                "max_total_chars",
                "TOMMY_BUDGET_MAX_TOTAL_CHARS",
                DEFAULT_MAX_TOTAL_CHARS,
            ),
        )
