from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_POSTGRES_DSN = os.getenv("TOMMY_TEST_POSTGRES_DSN", "dbname=tommy_agent_test")


def _admin_dsn(test_dsn: str) -> str:
    params = conninfo_to_dict(test_dsn)
    params["dbname"] = os.getenv("TOMMY_POSTGRES_ADMIN_DB", "postgres")
    return make_conninfo(**params)


def _test_database_name(test_dsn: str) -> str:
    params = conninfo_to_dict(test_dsn)
    dbname = str(params.get("dbname") or "")
    if not (dbname.endswith("_test") or dbname.startswith("test_")):
        raise RuntimeError("TOMMY_TEST_POSTGRES_DSN must point at a *_test or test_* database.")
    return dbname


def _ensure_test_database() -> None:
    dbname = _test_database_name(TEST_POSTGRES_DSN)
    with psycopg.connect(_admin_dsn(TEST_POSTGRES_DSN), autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (dbname,),
        ).fetchone()
        if exists is None:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))


_ensure_test_database()
os.environ["TOMMY_POSTGRES_DSN"] = TEST_POSTGRES_DSN
os.environ.setdefault("TOMMY_EMBEDDING_PROVIDER", "null")
