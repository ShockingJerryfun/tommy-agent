from __future__ import annotations


def test_product_schema_runner_exposes_versioned_bootstrap_sql() -> None:
    from app.agent_framework.storage.schema import (
        CURRENT_SCHEMA_VERSION,
        PROMPT_SEED_SQL,
        SCHEMA_DDL,
        schema_versions,
    )

    versions = schema_versions()

    assert CURRENT_SCHEMA_VERSION == versions[-1].version
    assert versions[0].version == 1
    assert "CREATE TABLE IF NOT EXISTS sessions" in SCHEMA_DDL
    assert "CREATE TABLE IF NOT EXISTS prompts" in SCHEMA_DDL
    assert "prompt-builtin-summarize" in PROMPT_SEED_SQL
    assert all("migration" not in version.name.lower() for version in versions)
