from __future__ import annotations

from typing import Any

from ..paths import DATA_ROOT, INDEX_ROOT, ROOT
from ..settings import settings_snapshot
from ..storage import PostgresAgentStore
from .checkpointing import checkpoint_status


def runtime_health(store: PostgresAgentStore) -> dict[str, Any]:
    return {
        "status": "ok",
        "app": {
            "name": "Tommy Agent Framework",
            "root": str(ROOT),
        },
        "config": settings_snapshot(),
        "paths": {
            "data_root": str(DATA_ROOT),
            "data_root_exists": DATA_ROOT.exists(),
            "index_root": str(INDEX_ROOT),
            "index_root_exists": INDEX_ROOT.exists(),
        },
        "storage": {
            "backend": store.backend,
            "dsn_configured": bool(store.dsn),
        },
        "checkpointing": checkpoint_status(),
    }
