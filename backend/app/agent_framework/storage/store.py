"""PostgreSQL-backed store composition."""

from __future__ import annotations

from ..settings import load_settings
from .repos import (
    ApprovalRepo,
    CompactionRepo,
    Connector,
    ConsolidationRunRepo,
    ContextPactRepo,
    EventRepo,
    MemoryInjectionRepo,
    MemoryRepo,
    MessageRepo,
    PromptRepo,
    PromptSnapshotRepo,
    RunControlRepo,
    RunMetricsRepo,
    RunRepo,
    SearchRepo,
    SessionRepo,
    SkillCatalogRepo,
    SkillForgeRunRepo,
    SkillRepo,
    StoredMessage,
    SubagentRunRepo,
    ToolArtifactRepo,
    ToolCallRepo,
    ensure_schema,
    reset_for_tests,
    utc_now,
)
from .store_facade.conversations import ConversationStoreMixin
from .store_facade.knowledge import KnowledgeStoreMixin
from .store_facade.prompts import PromptStoreMixin
from .store_facade.runs import RunStoreMixin

__all__ = ["PostgresAgentStore", "StoredMessage", "utc_now"]


class PostgresAgentStore(
    ConversationStoreMixin,
    RunStoreMixin,
    KnowledgeStoreMixin,
    PromptStoreMixin,
):
    """Composite store that delegates to focused repository modules."""

    backend = "postgres"

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or load_settings().postgres_dsn
        self._connector = Connector(self.dsn)
        self.sessions = SessionRepo(self._connector)
        self.messages = MessageRepo(self._connector)
        self.runs = RunRepo(self._connector)
        self.run_controls = RunControlRepo(self._connector)
        self.events = EventRepo(self._connector)
        self.tool_calls = ToolCallRepo(self._connector)
        self.tool_artifacts = ToolArtifactRepo(self._connector)
        self.approvals = ApprovalRepo(self._connector)
        self.memories = MemoryRepo(self._connector)
        self.skills = SkillRepo(self._connector)
        self.skill_catalog = SkillCatalogRepo(self._connector)
        self.skill_forge_runs = SkillForgeRunRepo(self._connector)
        self.subagent_runs = SubagentRunRepo(self._connector)
        self.run_metrics = RunMetricsRepo(self._connector)
        self.search = SearchRepo(self._connector)
        self.context_pacts = ContextPactRepo(self._connector)
        self.compactions = CompactionRepo(self._connector)
        self.prompts = PromptRepo(self._connector)
        self.prompt_snapshots = PromptSnapshotRepo(self._connector)
        self.memory_injections = MemoryInjectionRepo(self._connector)
        self.consolidation_runs = ConsolidationRunRepo(self._connector)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        ensure_schema(self._connector)

    def reset_for_tests(self) -> None:
        reset_for_tests(self._connector)
