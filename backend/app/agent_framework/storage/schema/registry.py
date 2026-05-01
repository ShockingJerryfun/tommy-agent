from __future__ import annotations

from dataclasses import dataclass

from .versions.v0001_core import CORE_DDL
from .versions.v0002_knowledge import KNOWLEDGE_DDL
from .versions.v0003_skills import SKILLS_DDL
from .versions.v0004_operations import OPERATIONS_DDL


@dataclass(frozen=True)
class SchemaVersion:
    version: int
    name: str
    ddl: str


_SCHEMA_VERSIONS = (
    SchemaVersion(1, "core runtime tables", CORE_DDL),
    SchemaVersion(2, "knowledge tables", KNOWLEDGE_DDL),
    SchemaVersion(3, "skill and delegation tables", SKILLS_DDL),
    SchemaVersion(4, "operations tables", OPERATIONS_DDL),
)

CURRENT_SCHEMA_VERSION = _SCHEMA_VERSIONS[-1].version
SCHEMA_DDL = "\n\n".join(version.ddl for version in _SCHEMA_VERSIONS)


def schema_versions() -> tuple[SchemaVersion, ...]:
    return _SCHEMA_VERSIONS
