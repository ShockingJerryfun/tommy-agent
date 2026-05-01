from __future__ import annotations

from ..repos._base import Connector, database_name_from_dsn, is_test_database_dsn
from .bootstrap import PROMPT_SEED_SQL
from .registry import SCHEMA_DDL

_TRUNCATE_SQL = """
TRUNCATE TABLE
    prompts,
    run_metrics,
    subagent_runs,
    skill_forge_runs,
    skills,
    tool_artifacts,
    memory_consolidation_runs,
    memory_injections,
    prompt_snapshots,
    approval_requests,
    compaction_runs,
    context_pacts,
    skill_versions,
    skill_proposals,
    memories,
    tool_calls,
    run_controls,
    runs,
    run_events,
    messages,
    sessions
CASCADE
"""


def ensure_schema(connector: Connector) -> None:
    with connector.connect() as conn:
        conn.executescript(SCHEMA_DDL)
        conn.executescript(PROMPT_SEED_SQL)


def reset_for_tests(connector: Connector) -> None:
    if not is_test_database_dsn(connector.dsn):
        dbname = database_name_from_dsn(connector.dsn) or "<unknown>"
        raise RuntimeError(
            "Refusing to reset a non-test database. "
            f"Current database is {dbname!r}; use TOMMY_POSTGRES_DSN with a *_test database."
        )
    with connector.connect() as conn:
        conn.execute(_TRUNCATE_SQL)
        conn.executescript(PROMPT_SEED_SQL)
