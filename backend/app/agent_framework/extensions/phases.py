"""Hook lifecycle phases.

Phases are deliberately enumerated and closed: extensions cannot
invent new phases at runtime. This keeps the dispatch surface small
and the audit log auditable.
"""

from __future__ import annotations

from enum import StrEnum


class HookPhase(StrEnum):
    """Closed set of lifecycle points where hooks may fire."""

    RUN_START = "run_start"
    RUN_END = "run_end"
    PRE_TOOL = "pre_tool"
    POST_TOOL = "post_tool"
    PRE_COMPACT = "pre_compact"
    POST_MEMORY_EXTRACT = "post_memory_extract"
    PRE_APPROVAL = "pre_approval"

    @classmethod
    def values(cls) -> list[str]:
        return [phase.value for phase in cls]
