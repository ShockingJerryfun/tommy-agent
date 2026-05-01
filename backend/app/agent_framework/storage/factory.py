from __future__ import annotations

from ..settings import RuntimeSettings, load_settings
from .store import PostgresAgentStore

_AGENT_STORE: PostgresAgentStore | None = None


def create_agent_store(settings: RuntimeSettings | None = None) -> PostgresAgentStore:
    active = settings or load_settings()
    return PostgresAgentStore(dsn=active.postgres_dsn)


def get_agent_store(settings: RuntimeSettings | None = None) -> PostgresAgentStore:
    global _AGENT_STORE
    if settings is not None:
        return create_agent_store(settings)
    if _AGENT_STORE is None:
        _AGENT_STORE = create_agent_store()
    return _AGENT_STORE
