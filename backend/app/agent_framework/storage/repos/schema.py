"""Compatibility wrapper for the product storage schema runner."""

from __future__ import annotations

from ..schema import (
    BUILTIN_PROMPTS,
    CURRENT_SCHEMA_VERSION,
    PROMPT_SEED_SQL,
    SCHEMA_DDL,
    SchemaVersion,
    build_prompt_seed_sql,
    ensure_schema,
    reset_for_tests,
    schema_versions,
)

__all__ = [
    "BUILTIN_PROMPTS",
    "CURRENT_SCHEMA_VERSION",
    "PROMPT_SEED_SQL",
    "SCHEMA_DDL",
    "SchemaVersion",
    "build_prompt_seed_sql",
    "ensure_schema",
    "reset_for_tests",
    "schema_versions",
]
