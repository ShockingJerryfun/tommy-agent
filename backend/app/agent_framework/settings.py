from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeSettings:
    storage_backend: str
    checkpoint_backend: str
    postgres_dsn: str


def load_settings() -> RuntimeSettings:
    postgres_dsn = os.getenv("TOMMY_POSTGRES_DSN", "").strip() or "dbname=tommy_agent"
    return RuntimeSettings(
        storage_backend="postgres",
        checkpoint_backend="postgres",
        postgres_dsn=postgres_dsn,
    )


def settings_snapshot(settings: RuntimeSettings | None = None) -> dict[str, str]:
    active = settings or load_settings()
    return {
        "storage_backend": active.storage_backend,
        "checkpoint_backend": active.checkpoint_backend,
        "postgres_dsn_configured": str(bool(active.postgres_dsn)).lower(),
    }
