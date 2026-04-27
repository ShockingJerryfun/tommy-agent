"""Alembic environment for Tommy.

Resolves the database URL from ``TOMMY_POSTGRES_DSN`` (libpq keyword/value
or URI form) and converts it to the SQLAlchemy + psycopg driver URL that
Alembic expects. The application itself uses ``psycopg`` directly; Alembic
only borrows SQLAlchemy as the migration driver.
"""

from __future__ import annotations

import os
from logging.config import fileConfig
from urllib.parse import quote_plus

from alembic import context
from psycopg.conninfo import conninfo_to_dict
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _resolve_sqlalchemy_url() -> str:
    raw = os.getenv("TOMMY_POSTGRES_DSN", "").strip() or "dbname=tommy_agent"
    if raw.startswith("postgresql://") or raw.startswith("postgres://"):
        return raw.replace("postgres://", "postgresql+psycopg://", 1).replace(
            "postgresql://", "postgresql+psycopg://", 1
        )
    params = conninfo_to_dict(raw)
    user = params.get("user") or ""
    password = params.get("password") or ""
    host = params.get("host") or "localhost"
    port = params.get("port") or "5432"
    dbname = params.get("dbname") or params.get("database") or ""
    auth = ""
    if user:
        auth = quote_plus(user)
        if password:
            auth = f"{auth}:{quote_plus(password)}"
        auth = f"{auth}@"
    return f"postgresql+psycopg://{auth}{host}:{port}/{dbname}"


config.set_main_option("sqlalchemy.url", _resolve_sqlalchemy_url())


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
