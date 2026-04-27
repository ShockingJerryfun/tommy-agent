"""Repository modules carved from the original monolithic store.

Each repo owns one domain table (or a small cluster) and depends only on
``_base.Connector`` for connection management. The composing object is
``PostgresAgentStore`` in the parent package, which exists as a thin
facade over these repos so that callers (and tests) keep their existing
import surface.
"""

from __future__ import annotations

from ._base import (
    Connector,
    StoredMessage,
    database_name_from_dsn,
    dumps,
    is_test_database_dsn,
    loads,
    refresh_session_summary,
    utc_now,
)
from .approvals import ApprovalRepo
from .compaction import CompactionRepo
from .consolidation import ConsolidationRunRepo
from .context_pacts import ContextPactRepo
from .events import EventRepo
from .memories import MemoryRepo
from .messages import MessageRepo
from .prompts import MemoryInjectionRepo, PromptSnapshotRepo
from .run_controls import RunControlRepo
from .run_metrics import RunMetricsRepo
from .runs import RunRepo
from .schema import ensure_schema, reset_for_tests
from .sessions import SessionRepo
from .skill_catalog import SkillCatalogRepo
from .skill_forge_runs import SkillForgeRunRepo
from .skills import SkillRepo
from .subagent_runs import SubagentRunRepo
from .tool_artifacts import ToolArtifactRepo
from .tool_calls import ToolCallRepo

__all__ = [
    "ApprovalRepo",
    "CompactionRepo",
    "Connector",
    "ConsolidationRunRepo",
    "ContextPactRepo",
    "EventRepo",
    "MemoryInjectionRepo",
    "MemoryRepo",
    "MessageRepo",
    "PromptSnapshotRepo",
    "RunMetricsRepo",
    "RunControlRepo",
    "RunRepo",
    "SessionRepo",
    "SkillCatalogRepo",
    "SkillForgeRunRepo",
    "SkillRepo",
    "StoredMessage",
    "SubagentRunRepo",
    "ToolArtifactRepo",
    "ToolCallRepo",
    "database_name_from_dsn",
    "dumps",
    "ensure_schema",
    "is_test_database_dsn",
    "loads",
    "refresh_session_summary",
    "reset_for_tests",
    "utc_now",
]
