from __future__ import annotations

from .v0001_core import CORE_DDL
from .v0002_knowledge import KNOWLEDGE_DDL
from .v0003_skills import SKILLS_DDL
from .v0004_operations import OPERATIONS_DDL
from .v0005_multi_agent import MULTI_AGENT_DDL
from .v0006_production_multi_agent import PRODUCTION_MULTI_AGENT_DDL

__all__ = [
    "CORE_DDL",
    "KNOWLEDGE_DDL",
    "MULTI_AGENT_DDL",
    "OPERATIONS_DDL",
    "PRODUCTION_MULTI_AGENT_DDL",
    "SKILLS_DDL",
]
